import pytest, os, hashlib, json
from pathlib import Path
from lib.cockpit_brand_summary import brand_summary

def _snapshot_tree(p: Path):
    return {str(x): (x.stat().st_mtime_ns, x.stat().st_size) for x in p.rglob("*") if x.is_file()}

def test_comprehensive_brand_summary(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    tenants_dir = data_root / "tenants"
    tenants_dir.mkdir()
    t_dir = tenants_dir / "acme-corp"
    t_dir.mkdir()
    
    # 1. Context Files in tenant_dir/context
    ctx_dir = t_dir / "context"
    ctx_dir.mkdir()
    for f in ["company.md", "customer.md", "offer.md", "open-questions.md", "owner.md", "proof.md", "voice.md", "extra.md"]:
        (ctx_dir / f).write_text("context data")
    
    # 2. Ingest plan with relative, foreign, and stale abs
    snap_file = t_dir / "docs" / "guide.md"
    snap_file.parent.mkdir(parents=True)
    snap_content = b"secure content test 123"
    snap_file.write_bytes(snap_content)
    snap_sha = hashlib.sha256(snap_content).hexdigest()
    
    plan = {
        "tenant": "acme-corp",
        "files": [
            {"path": "tenants/acme-corp/docs/guide.md"},
            {"path": "/Volumes/old/workspace/tenants/acme-corp/docs/guide.md"},
            {"path": "tenants/acme-corp/missing.md"},
            {"path": "tenants/other-corp/secret.md"},
            {"path": "../evil.md"},
            {"path": "bare_path.md"},
            {"path": "tenants/acme-corp/"},
            {"path": "tenants/acme-corp/tenants/file.md"},
            {"path": "tenants/acme-corp/bad\x00.md"},
            {"path": "tenants/acme-corp/bad\\slash.md"},
            {"path": 123}
        ]
    }
    (t_dir / "ingest-plan.json").write_text(json.dumps(plan))
    
    # 3. Research Provenance
    res_dir = t_dir / "wiki" / "research" / "batch1"
    res_dir.mkdir(parents=True)
    drift_file = t_dir / "docs" / "drift.md"
    drift_file.write_text("drifted")
    
    big_file = t_dir / "docs" / "large.bin"
    big_file.write_bytes(b"x" * 500001)
    
    prov = {
        "tenant": "acme-corp",
        "files": [
            {"snapshot": "tenants/acme-corp/docs/guide.md", "sha256": snap_sha},
            {"snapshot": "tenants/acme-corp/docs/drift.md", "sha256": "0"*64},
            {"snapshot": "tenants/acme-corp/docs/missing.md", "sha256": "1"*64},
            {"snapshot": "tenants/acme-corp/docs/large.bin", "sha256": "2"*64},
            {"snapshot": "tenants/other/f.md", "sha256": "3"*64},
            "invalid_record"
        ]
    }
    (res_dir / "provenance.json").write_text(json.dumps(prov))
    
    # 4. Specs: Org & Proposal
    spec_dir = data_root / "specs" / "006-editorial-steward-integration"
    spec_dir.mkdir(parents=True)
    org = {
        "desk_templates": [
            {"id": "editorial", "status": "proposed"},
            {"id": "growth", "status": "active"},
            {"id": "deprecated-desk", "status": "archived"},
            {"id": "INVALID_DESK!", "status": "proposed"}
        ]
    }
    (spec_dir / "organization.json").write_text(json.dumps(org))
    
    pmap = {
        "portfolio": {"id": "parent-holdings"},
        "branches": [
            {"id": "acme-corp", "parent": "parent-holdings", "relationship": "product_wing"},
            {"id": "other-wing", "parent": "parent-holdings"}
        ],
        "projects": [
            {"id": "proj-1", "parent": "acme-corp", "name": "Project bearer token=secret123456", "status": "malicious_active"},
            {"id": "proj-foreign", "parent": "other-wing", "name": "Foreign"}
        ],
        "cross_brand_flows": [
            {"id": "flow-sync", "participants": ["acme-corp", "other-wing"], "status": "approved"}
        ]
    }
    (spec_dir / "portfolio-map-proposal.json").write_text(json.dumps(pmap))
    
    before_snap = _snapshot_tree(data_root)
    
    # Execute
    res = brand_summary(data_root, t_dir, {"tenant": "acme-corp", "sources": [{"id": "s1", "type": "doc", "ingest": True}]})
    
    # Verification
    assert res["knowledge"]["contextFiles"] == 7
    assert res["knowledge"]["registeredSources"] == 1
    assert res["knowledge"]["admittedSources"] == 1
    assert res["knowledge"]["plannedFiles"] == 3
    assert res["knowledge"]["presentFiles"] == 2
    assert res["knowledge"]["missingFiles"] == 1
    assert res["knowledge"]["rejectedFiles"] == 8
    assert res["knowledge"]["researchFiles"] == 6
    assert res["knowledge"]["researchVerified"] == 1
    assert res["knowledge"]["researchMissing"] == 1
    assert res["knowledge"]["researchDrift"] == 1
    assert res["knowledge"]["researchRejected"] == 3
    assert res["knowledge"]["provenanceStatus"] == "drift"
    
    assert res["planning"]["desks"] == ["editorial"]
    assert res["planning"]["parent"] == "parent-holdings"
    assert res["planning"]["relationship"] == "product_wing"
    assert len(res["planning"]["projects"]) == 1
    assert res["planning"]["projects"][0]["status"] == "planning_not_provisioned"
    assert "secret123456" not in res["planning"]["projects"][0]["name"]
    assert res["planning"]["flows"][0]["status"] == "proposed_not_approved"
    
    after_snap = _snapshot_tree(data_root)
    assert before_snap == after_snap

def test_symlinks_and_invariants(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    tenants_dir = data_root / "tenants"
    tenants_dir.mkdir()
    t_dir = tenants_dir / "corp"
    t_dir.mkdir()
    
    sym_tenant = tmp_path / "sym_corp"
    try:
        sym_tenant.symlink_to(t_dir, target_is_directory=True)
        with pytest.raises(ValueError):
            brand_summary(data_root, sym_tenant, None)
    except (OSError, NotImplementedError):
        pass
    
    with pytest.raises(ValueError):
        brand_summary(data_root, tmp_path / "other", None)


def test_research_symlink_is_rejected(tmp_path):
    root = tmp_path / "data"
    tenant = root / "tenants" / "corp"
    batch = tenant / "wiki" / "research" / "batch"
    batch.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private secret")
    (tenant / "escape.txt").symlink_to(outside)
    (batch / "provenance.json").write_text(json.dumps({"tenant":"corp", "files":[{"snapshot":"tenants/corp/escape.txt", "sha256":hashlib.sha256(outside.read_bytes()).hexdigest()}]}))
    summary = brand_summary(root, tenant, None)
    assert summary["knowledge"]["researchRejected"] == 1
    assert summary["knowledge"]["researchVerified"] == 0
    assert str(tmp_path) not in json.dumps(summary)
    assert "private secret" not in json.dumps(summary)

def test_snapshot_private_projection_and_public_isolation(tmp_path, monkeypatch):
    from lib.cockpit_snapshot import build_snapshot
    repo = Path(__file__).resolve().parents[1]
    root = tmp_path / "data"
    tenant = root / "tenants" / "corp"
    tenant.mkdir(parents=True)
    monkeypatch.setenv("SNOWGLOVES_DATA", str(root))
    public = build_snapshot(repo, probe=False)
    assert all("knowledge" not in item for item in public["tenants"])
    private = build_snapshot(repo, data_root=root, tenant="corp", probe=False)
    assert [item["slug"] for item in private["tenants"]] == ["corp"]
    assert private["tenants"][0]["knowledge"]["status"] == "source-plan-only"

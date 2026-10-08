"""Unit tests for cockpit snapshot, document reader, and plan preview."""

import json
import os
from pathlib import Path
import pytest
import yaml

from lib.cockpit_snapshot import build_snapshot, read_document, preview_plan


def _private_fleet(tmp_path: Path) -> Path:
    data = tmp_path / 'private-fleet'
    data.mkdir()
    (data / 'tenants' / 't1').mkdir(parents=True)
    (data / 'tenants' / 't1' / 'MANIFEST.yaml').write_text('name: Private One\n')
    wings = {}
    for wing in ('coding', 'design', 'marketing'):
        host = f'{wing}-private-machine'
        wings[wing] = {'hostname': host, 'overlay': '10.2.3.4', 'operator_user': 'PRIVATE_OPERATOR'}
        directory = data / 'nodes' / wing
        directory.mkdir(parents=True)
        (directory / 'node.yaml').write_text(yaml.safe_dump({'wing': wing, 'hostname': host, 'primary': 'codex', 'modules': [], 'connectors': [], 'runtimes': ['codex']}))
    (data / 'fleet.yaml').write_text(yaml.safe_dump({'wings': wings, 'token': 'PRIVATE_TOKEN'}))
    return data


def _register_island(data: Path, node_id='mac-coding-2', wing='coding', hostname='second-private-machine'):
    inventory_path = data / 'fleet.yaml'
    inventory = yaml.safe_load(inventory_path.read_text())
    inventory.setdefault('islands', {})[node_id] = {'wing': wing, 'hostname': hostname}
    inventory_path.write_text(yaml.safe_dump(inventory))
    profile = data / 'nodes' / 'islands' / node_id / 'node.yaml'
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(yaml.safe_dump({'wing': wing, 'hostname': hostname, 'primary': 'codex'}))
    return profile


def test_fourth_island_registration_has_own_verified_profile(fixture_repo, tmp_path):
    data = _private_fleet(tmp_path)
    _register_island(data)
    audit = data / '_audit'
    audit.mkdir()
    (audit / 'jobs.jsonl').write_text(json.dumps({'id': 'coding-two-job', 'tenant': 't1', 'hostname': 'second-private-machine', 'agent': 'cto', 'status': 'running'}))
    snap = build_snapshot(fixture_repo, data_root=data, tenant='t1', probe=False)
    assert all(n['assignment'] == 'configured' for n in snap['fleetNodes'])
    assert len(snap['fleet']) == 3  # Per-slot profiles do not duplicate wing contracts.
    second = snap['fleetNodes'][1]
    assert second['profileId'] == 'node-coding'
    assert second['sources'] == ['catalog/fleet-topology.json', 'fleet.yaml', 'nodes/islands/mac-coding-2/node.yaml']
    assert second['observedAt'] is None
    assert snap['activity']['jobs'][0]['nodeId'] == 'mac-coding-2'
    assert 'second-private-machine' not in json.dumps(snap)


@pytest.mark.parametrize('failure', ['missing', 'hostname', 'wing', 'symlink', 'entry-wing', 'extra-field'])
def test_explicit_invalid_island_never_falls_back_to_legacy(fixture_repo, tmp_path, failure):
    data = _private_fleet(tmp_path)
    profile = _register_island(data, node_id='mac-coding-1', hostname='explicit-private-machine')
    if failure == 'missing':
        profile.unlink()
    elif failure == 'hostname':
        profile.write_text('wing: coding\nhostname: disagreement\n')
    elif failure == 'wing':
        profile.write_text('wing: marketing\nhostname: explicit-private-machine\n')
    elif failure == 'symlink':
        profile.unlink()
        profile.symlink_to(data / 'nodes' / 'coding' / 'node.yaml')
    else:
        inventory_path = data / 'fleet.yaml'
        inventory = yaml.safe_load(inventory_path.read_text())
        if failure == 'entry-wing':
            inventory['islands']['mac-coding-1']['wing'] = 'marketing'
        else:
            inventory['islands']['mac-coding-1']['ssh_command'] = 'SECRET_COMMAND'
        inventory_path.write_text(yaml.safe_dump(inventory))
    snap = build_snapshot(fixture_repo, data_root=data, probe=False)
    assert [n['assignment'] for n in snap['fleetNodes']] == ['planned', 'planned', 'configured', 'configured']
    assert 'SECRET_COMMAND' not in json.dumps(snap)


@pytest.mark.parametrize('hostname', ['coding-private-machine', 'CODING-PRIVATE-MACHINE'])
def test_explicit_island_cannot_clone_legacy_machine(fixture_repo, tmp_path, hostname):
    data = _private_fleet(tmp_path)
    _register_island(data, hostname=hostname)
    snap = build_snapshot(fixture_repo, data_root=data, probe=False)
    assert [n['assignment'] for n in snap['fleetNodes']] == ['planned', 'planned', 'configured', 'configured']
    assert 'fleet_binding_ambiguous' in [w['code'] for w in snap['warnings']]


@pytest.mark.parametrize('invalid_map', [[], {'../../extra': {'wing': 'coding', 'hostname': 'extra'}},
    {f'extra-{i}': {'wing': 'coding', 'hostname': f'host-{i}'} for i in range(5)}])
def test_island_map_is_bounded_and_canonical(fixture_repo, tmp_path, invalid_map):
    data = _private_fleet(tmp_path)
    inventory_path = data / 'fleet.yaml'
    inventory = yaml.safe_load(inventory_path.read_text())
    inventory['islands'] = invalid_map
    inventory_path.write_text(yaml.safe_dump(inventory))
    snap = build_snapshot(fixture_repo, data_root=data, probe=False)
    assert len(snap['fleetNodes']) == 4
    assert all(n['assignment'] == 'planned' for n in snap['fleetNodes'])
    assert 'fleet_islands_held' in [w['code'] for w in snap['warnings']]


def test_explicit_islands_work_without_legacy_wings_and_public_stays_template(fixture_repo, tmp_path, monkeypatch):
    data = _private_fleet(tmp_path)
    from lib.cockpit_snapshot import FLEET_TOPOLOGY
    for node in FLEET_TOPOLOGY:
        _register_island(data, node['id'], node['wing'], f"{node['id']}-private-host")
    inventory_path = data / 'fleet.yaml'
    inventory = yaml.safe_load(inventory_path.read_text())
    del inventory['wings']
    inventory_path.write_text(yaml.safe_dump(inventory))
    assert all(n['assignment'] == 'configured' for n in build_snapshot(fixture_repo, data_root=data, probe=False)['fleetNodes'])
    monkeypatch.setenv('SNOWGLOVES_DATA', str(data))
    public = build_snapshot(fixture_repo, probe=False)
    assert all(n['assignment'] == 'template' and n['sources'] == ['catalog/fleet-topology.json'] for n in public['fleetNodes'])
    assert 'private-host' not in json.dumps(public)


def test_four_fleet_slots_public_templates_ignore_private_inventory(fixture_repo, tmp_path, monkeypatch):
    data = _private_fleet(tmp_path)
    monkeypatch.setenv('SNOWGLOVES_DATA', str(data))
    snap = build_snapshot(fixture_repo, probe=False)
    nodes = snap['fleetNodes']
    assert [n['id'] for n in nodes] == ['mac-coding-1', 'mac-coding-2', 'mac-creative', 'mac-marketing']
    assert [n['wing'] for n in nodes] == ['coding', 'coding', 'design', 'marketing']
    assert all(n['assignment'] == 'template' and n['evidence'] == 'source' and n['observedAt'] is None for n in nodes)
    assert all(n['sources'] == ['catalog/fleet-topology.json'] for n in nodes)
    assert 'private-machine' not in json.dumps(snap)


def test_private_fleet_assignments_require_verified_profiles(fixture_repo, tmp_path):
    data = _private_fleet(tmp_path)
    snap = build_snapshot(fixture_repo, data_root=data, probe=False)
    assert [n['assignment'] for n in snap['fleetNodes']] == ['configured', 'planned', 'configured', 'configured']
    assert all(n['observedAt'] is None for n in snap['fleetNodes'])
    dumped = json.dumps(snap)
    assert not any(secret in dumped for secret in ['private-machine', 'PRIVATE_OPERATOR', 'PRIVATE_TOKEN', '10.2.3.4'])
    assert 'inventory_identity_withheld' in [w['code'] for w in snap['warnings']]
    assert 'inventory_not_projected' not in [w['code'] for w in snap['warnings']]
    (data / 'nodes' / 'coding' / 'node.yaml').write_text('wing: coding\nhostname: mismatch\n')
    assert build_snapshot(fixture_repo, data_root=data, probe=False)['fleetNodes'][0]['assignment'] == 'planned'


def test_private_duplicate_inventory_binding_is_held(fixture_repo, tmp_path):
    data = _private_fleet(tmp_path)
    inventory = yaml.safe_load((data / 'fleet.yaml').read_text())
    inventory['wings']['design']['hostname'] = inventory['wings']['coding']['hostname']
    (data / 'fleet.yaml').write_text(yaml.safe_dump(inventory))
    profile = data / 'nodes' / 'design' / 'node.yaml'
    profile.write_text(yaml.safe_dump({'wing': 'design', 'hostname': inventory['wings']['coding']['hostname']}))
    snap = build_snapshot(fixture_repo, data_root=data, probe=False)
    assert [n['assignment'] for n in snap['fleetNodes']] == ['planned', 'planned', 'planned', 'configured']
    assert 'fleet_binding_ambiguous' in [w['code'] for w in snap['warnings']]


@pytest.mark.parametrize('mode', ['symlink', 'oversized', 'duplicates', 'unsafe-id'])
def test_topology_malformed_input_cannot_expand_or_relabel_roster(fixture_repo, tmp_path, mode):
    data = _private_fleet(tmp_path)
    topology = fixture_repo / 'catalog' / 'fleet-topology.json'
    if mode == 'symlink':
        outside = tmp_path / 'outside.json'
        outside.write_text('{"nodes": []}')
        topology.symlink_to(outside)
    elif mode == 'oversized':
        topology.write_text(' ' * 8193)
    else:
        from lib.cockpit_snapshot import FLEET_TOPOLOGY
        nodes = [dict(n) for n in FLEET_TOPOLOGY]
        if mode == 'duplicates':
            nodes[1] = nodes[0]
        else:
            nodes[0]['id'] = '../../private-device'
        topology.write_text(json.dumps({'schema': 'snowgloves.fleet-topology.v1', 'nodes': nodes}))
    snap = build_snapshot(fixture_repo, data_root=data, probe=False)
    assert len(snap['fleetNodes']) == 4
    assert all(n['assignment'] == 'planned' for n in snap['fleetNodes'])
    assert 'fleet_topology_held' in [w['code'] for w in snap['warnings']]


def test_activity_exact_node_and_unique_host_attribution_preserve_unassigned(fixture_repo, tmp_path):
    data = _private_fleet(tmp_path)
    audit = data / '_audit'
    audit.mkdir()
    rows = [
        {'id': 'canonical', 'nodeId': 'mac-coding-1'},
        {'id': 'alias', 'node_id': 'mac-creative'},
        {'id': 'node', 'node': 'mac-marketing'},
        {'id': 'verified-host', 'hostname': 'coding-private-machine'},
        {'id': 'verified-node-host', 'node': 'design-private-machine'},
        {'id': 'wing-only', 'wing': 'coding'},
        {'id': 'unknown', 'nodeId': 'unknown'},
        {'id': 'unsafe', 'node': '../../private'},
        {'id': 'conflicting', 'nodeId': 'mac-coding-1', 'node_id': 'mac-coding-2'},
        {'id': 'unassigned'},
        {'id': 'foreign', 'nodeId': 'mac-coding-1', 'tenant': 't2'},
        {'id': 'terminal', 'status': 'cancelled', 'jobId': 'j1', 'agent': None},
    ]
    for row in rows:
        row.setdefault('tenant', 't1')
        row.setdefault('agent', 'cto')
        row.setdefault('status', 'running')
    (audit / 'jobs.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    snap = build_snapshot(fixture_repo, data_root=data, tenant='t1', probe=False)
    jobs = {r['id']: r for r in snap['activity']['jobs']}
    assert jobs['canonical']['nodeId'] == 'mac-coding-1'
    assert jobs['alias']['nodeId'] == 'mac-creative'
    assert jobs['node']['nodeId'] == 'mac-marketing'
    assert jobs['verified-host']['nodeId'] == 'mac-coding-1'
    assert jobs['verified-node-host']['nodeId'] == 'mac-creative'
    assert all(jobs[r]['nodeId'] is None for r in ['wing-only', 'unknown', 'unsafe', 'conflicting', 'unassigned', 'terminal'])
    assert jobs['terminal']['agent'] is None
    assert 'foreign' not in jobs
    assert 'private-machine' not in json.dumps(snap['activity'])


def test_repository_routing_source_shape():
    root = Path(__file__).resolve().parents[1]
    snap = build_snapshot(root, probe=False)
    assert len(snap["routing"]["rules"]) >= 20
    assert len(snap["routing"]["skills"]) == 4
    assert all(skill["id"].startswith("snowgloves:") for skill in snap["routing"]["skills"])
    plan = preview_plan(root, {"tenant": "acme", "title": "build architecture", "modules": []})
    assert any(route["agent"] == "cto" and route["hook"] == "architecture-and-execution" for route in plan["routes"])


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    # catalog/modules.json
    catalog_dir = repo / "catalog"
    catalog_dir.mkdir()
    catalog_data = {
        "schema": "snowgloves.catalog.v1",
        "version": "1.0.0",
        "cards": [
            {"id": "mod-allowed", "name": "Allowed Module", "status": "active", "risk": "low"},
            {"id": "mod-approval", "name": "Approval Module", "status": "active", "risk": "high"},
            {"id": "mod-held", "name": "Held Module", "status": "hold", "risk": "low"},
        ],
        "connectors": [
            {"id": "conn-slack", "name": "Slack Connector", "status": "active", "risk": "low"}
        ],
        "counts": {"cards": 3, "connectors": 1}
    }
    (catalog_dir / "modules.json").write_text(json.dumps(catalog_data))
    (catalog_dir / "SCHEMA.md").write_text("# Catalog Schema\nDoc content")

    # tenants/t1
    t1 = repo / "tenants" / "t1"
    t1.mkdir(parents=True)
    (t1 / "MANIFEST.yaml").write_text(yaml.dump({"name": "Tenant One", "secret_token": "LEAK_ME_NOT"}))
    (t1 / "runtime.yaml").write_text(yaml.dump({"primary": "local-process"}))
    (t1 / "enabled.yaml").write_text(yaml.dump({"modules": ["mod-allowed", "mod-approval", "mod-held"], "agents": ["cto"]}))
    (t1 / "sources.yaml").write_text(yaml.dump({"sources": [{"path": "/private/path/dont/leak", "kind": "git"}]}))

    # approvals in t1
    app_dir = t1 / "approvals"
    app_dir.mkdir()
    (app_dir / "app1.yaml").write_text(yaml.dump({"status": "pending", "notes": "secret-notes"}))
    (app_dir / "app2.json").write_text(json.dumps({"status": "approved"}))

    # nodes/alpha/node.yaml
    node_dir = repo / "nodes" / "alpha"
    node_dir.mkdir(parents=True)
    (node_dir / "node.yaml").write_text(yaml.dump({
        "wing": "alpha",
        "primary": "local-process",
        "runtimes": ["local-process"],
        "modules": ["mod-allowed", "mod-approval"],
        "connectors": ["conn-slack"],
        "services": [{"id": "svc1", "port": 8080, "secret_env": "HIDDEN"}],
        "hostname": "secret-host.lan",
        "operator_user": "admin_secret"
    }))

    # workflows
    wf_dir = repo / "workflows"
    wf_dir.mkdir()
    (wf_dir / "constraints.yaml").write_text(yaml.dump({
        "constraints": [
            {
                "id": "c-bug",
                "when": {"globs": ["*bug*", "*fix*"]},
                "then": {"agent": "cto", "hook": "review-fix", "skills": ["debugger"]}
            }
        ]
    }))
    (wf_dir / "skill-hooks.yaml").write_text(yaml.dump({
        "hooks": [
            {"id": "h1", "name": "deploy-hook", "agent": "cto", "globs": ["*deploy*"], "skills": ["deployer"]}
        ]
    }))

    # skills
    sk_dir = repo / "skills"
    sk_dir.mkdir()
    (sk_dir / "registry.yaml").write_text(yaml.dump({
        "agents": {"cto": ["debugger", "deployer"]}
    }))

    # ISA.md
    (repo / "ISA.md").write_text("""# ISA
Some text that should be ignored
| ID | Criterion | Status |
|---|---|---|
- [x] ISC-101: Must isolate private tokens
- [x] ISC-102: Must refuse held modules
- [ ] ISC-103: Open requirement
""")

    # README.md
    (repo / "README.md").write_text("# Snowgloves Repo\nHello World")

    return repo


def test_snapshot_structure_and_scope(fixture_repo: Path):
    snap = build_snapshot(fixture_repo, probe=False)
    assert snap["schema"] == "snowgloves.cockpit.v1"
    assert snap["scope"]["mode"] == "public-fixtures"
    assert snap["scope"]["readOnly"] is True
    assert snap["capabilities"]["planPreview"] is True
    assert snap["capabilities"]["execute"] is False
    assert len(snap["tenants"]) == 1
    t = snap["tenants"][0]
    assert t["slug"] == "t1"
    assert t["name"] == "Tenant One"
    assert "secret_token" not in json.dumps(t)
    assert t["approvalCounts"] == {"pending": 1, "approved": 1, "rejected": 0}
    assert t["sources"] == ["tenants/t1/sources.yaml"]


def test_node_secret_omission(fixture_repo: Path):
    snap = build_snapshot(fixture_repo, probe=False)
    assert len(snap["fleet"]) == 1
    node = snap["fleet"][0]
    assert node["wing"] == "alpha"
    dumped = json.dumps(node)
    assert "secret-host.lan" not in dumped
    assert "admin_secret" not in dumped
    assert "secret_env" not in dumped
    assert node["profile"]["services"] == [{"id": "svc1", "port": 8080}]


def test_activity_tenant_filtering(fixture_repo: Path, tmp_path: Path):
    data_root = tmp_path / "data"
    audit_dir = data_root / "_audit"
    audit_dir.mkdir(parents=True)
    (data_root / "tenants" / "t1").mkdir(parents=True, exist_ok=True)

    events_file = audit_dir / "hermes-events.jsonl"
    events_file.write_text("""
{"id": "e1", "tenant": "t1", "agent": "cto", "kind": "event", "status": "done"}
{"id": "e2", "tenant": "t2", "agent": "ceo", "kind": "event", "status": "done"}
{"id": "e3", "agent": "cto", "kind": "event", "status": "done"}
""".strip())

    # Gated to tenant t1: must only see t1
    snap = build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)
    assert snap["scope"]["mode"] == "local-private"
    events = snap["activity"]["events"]
    assert len(events) == 1
    assert events[0]["id"] == "e1"
    assert events[0]["tenant"] == "t1"


def test_malformed_jsonl_tail_warning(fixture_repo: Path, tmp_path: Path):
    data_root = tmp_path / "data"
    audit_dir = data_root / "_audit"
    audit_dir.mkdir(parents=True)
    (data_root / "tenants" / "t1").mkdir(parents=True, exist_ok=True)
    events_file = audit_dir / "hermes-events.jsonl"
    events_file.write_text('VALID JSON NO TENANT\n{BAD JSON\n{"id": "e10", "tenant": "t1"}\n')

    snap = build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)
    codes = [w["code"] for w in snap["warnings"]]
    assert "audit_malformed_rows" in codes


def test_isa_criterion_parsing(fixture_repo: Path):
    snap = build_snapshot(fixture_repo, probe=False)
    acc = snap["acceptance"]
    assert len(acc) == 3
    assert acc[0]["id"] == "ISC-101"
    assert acc[0]["status"] == "accepted"
    assert acc[1]["id"] == "ISC-102"
    assert acc[1]["status"] == "accepted"
    assert acc[2]["id"] == "ISC-103"
    assert acc[2]["status"] == "open"


def test_read_document_allowlist_and_truncation(fixture_repo: Path):
    # 1. Allowed document
    doc = read_document(fixture_repo, "README.md")
    assert doc["schema"] == "snowgloves.cockpit.document.v1"
    assert doc["path"] == "README.md"
    assert doc["content"] == "# Snowgloves Repo\nHello World"
    assert doc["truncated"] is False
    assert len(doc["sha256"]) == 64

    # 2. Disallowed or traversal path
    with pytest.raises(Exception):
        read_document(fixture_repo, "tenants/t1/MANIFEST.yaml")
    with pytest.raises(Exception):
        read_document(fixture_repo, "../outside.txt")
    with pytest.raises(Exception):
        read_document(fixture_repo, "README.md\0.txt")


def test_read_only_guarantee(fixture_repo: Path):
    mtimes_before = {}
    for p in fixture_repo.rglob("*"):
        if p.is_file():
            mtimes_before[p] = p.stat().st_mtime

    _ = build_snapshot(fixture_repo, probe=False)
    _ = read_document(fixture_repo, "README.md")
    _ = preview_plan(fixture_repo, {"tenant": "t1", "title": "Fix bug in system", "modules": ["mod-allowed"]})

    for p in fixture_repo.rglob("*"):
        if p.is_file():
            assert p.stat().st_mtime == mtimes_before[p]


def test_plan_preview_decisions(fixture_repo: Path):
    payload = {
        "tenant": "t1",
        "title": "Fix bug in auth",
        "modules": ["mod-allowed", "mod-approval", "mod-held", "mod-unknown"],
        "wing": "alpha"
    }
    plan = preview_plan(fixture_repo, payload)
    assert plan["schema"] == "snowgloves.cockpit.plan.v1"
    assert plan["tenant"] == "t1"
    assert plan["executable"] is False
    assert len(plan["routes"]) > 0
    assert plan["routes"][0]["agent"] == "cto"

    decs = {m["id"]: m["decision"] for m in plan["modules"]}
    assert decs["mod-allowed"] == "allowed"
    assert decs["mod-approval"] == "approval-required"
    assert decs["mod-held"] == "refused"
    assert decs["mod-unknown"] == "unknown"


def test_plan_preview_strict_validation(fixture_repo: Path):
    # Missing tenant
    with pytest.raises(ValueError):
        preview_plan(fixture_repo, {"title": "No tenant", "modules": []})

    # Unknown payload keys
    with pytest.raises(ValueError):
        preview_plan(fixture_repo, {"tenant": "t1", "title": "Plan", "modules": [], "extra": 123})

    # Non-existent tenant
    with pytest.raises(LookupError):
        preview_plan(fixture_repo, {"tenant": "non_existent", "title": "Plan", "modules": []})


def test_no_probe_services(fixture_repo: Path):
    snap = build_snapshot(fixture_repo, probe=False)
    for svc in snap["services"]:
        assert svc["state"] == "unknown"
        assert svc["checkedAt"] is None
        assert svc["latencyMs"] is None


def test_private_selected_tenant_must_exist_privately(fixture_repo: Path, tmp_path: Path):
    data_root = tmp_path / "data"
    tenants_dir = data_root / "tenants"
    tenants_dir.mkdir(parents=True)
    # data/tenants exists but tenant t1 does not exist in data_root
    with pytest.raises(ValueError, match="unknown_tenant"):
        build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)

    # Now create explicit private t1 under data/tenants/t1
    t1_private = tenants_dir / "t1"
    t1_private.mkdir(parents=True)
    (t1_private / "MANIFEST.yaml").write_text(yaml.dump({"name": "Private Tenant One"}))

    snap = build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)
    assert snap["scope"]["mode"] == "local-private"
    assert len(snap["tenants"]) == 1
    assert snap["tenants"][0]["slug"] == "t1"
    assert snap["tenants"][0]["name"] == "Private Tenant One"
    assert snap["tenants"][0]["availability"] == "local"

def test_public_default_ignores_environment_and_loads_public(fixture_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_root = tmp_path / "env_data"
    t_dir = data_root / "tenants" / "env_tenant"
    t_dir.mkdir(parents=True)
    (t_dir / "MANIFEST.yaml").write_text(yaml.dump({"name": "Env Tenant"}))

    monkeypatch.setenv("SNOWGLOVES_DATA_ROOT", str(data_root))
    monkeypatch.setenv("DATA_ROOT", str(data_root))

    snap = build_snapshot(fixture_repo, data_root=None, probe=False)
    assert snap["scope"]["mode"] == "public-fixtures"
    assert len(snap["tenants"]) == 1
    assert snap["tenants"][0]["slug"] == "t1"
    assert snap["tenants"][0]["availability"] == "fixture"

def test_activity_events_parsing_and_tenant_filtering(fixture_repo: Path, tmp_path: Path):
    data_root = tmp_path / "data"
    t1_dir = data_root / "tenants" / "t1"
    t1_dir.mkdir(parents=True)
    audit_dir = data_root / "_audit"
    audit_dir.mkdir(parents=True)
    (data_root / "tenants" / "t1").mkdir(parents=True, exist_ok=True)

    events_file = audit_dir / "hermes-events.jsonl"
    events_file.write_text("\n".join([
        json.dumps({"id": "e_num", "tenant": "t1", "ts": 1700000000, "status": "active"}),
        json.dumps({"id": "e_nostat_nots", "tenant": "t1"}),
        json.dumps({"id": "e_other_tenant", "tenant": "t2", "ts": 1700000001}),
        json.dumps({"id": "e_no_tenant", "ts": 1700000002}),
    ]) + "\n")

    snap = build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)
    events = snap["activity"]["events"]
    assert len(events) == 2

    ev_num = next(e for e in events if e["id"] == "e_num")
    assert ev_num["timestamp"] == "1700000000"
    assert ev_num["status"] == "active"

    ev_nostat = next(e for e in events if e["id"] == "e_nostat_nots")
    assert ev_nostat["timestamp"] is None
    assert ev_nostat["status"] == "unknown"

def test_approvals_jsonl_counts_activity_and_redaction(fixture_repo: Path, tmp_path: Path):
    data_root = tmp_path / "data"
    t1_app = data_root / "tenants" / "t1" / "approvals"
    t1_app.mkdir(parents=True)

    pending_records = [
        {"id": "p1", "tenant": "t1", "status": "pending", "created_at": "2023-01-01T00:00:00Z"},
        {"id": "p2", "tenant": "t1", "decision": "pending", "created_at": "2023-01-01T01:00:00Z"},
    ]
    (t1_app / "pending.jsonl").write_text("\n".join(json.dumps(r) for r in pending_records) + "\n{BAD PENDING JSON\n")

    history_records = [
        {"id": "h1", "tenant": "t1", "status": "approved", "created_at": "2023-01-01T02:00:00Z", "decided_at": "2023-01-01T03:00:00Z"},
        {"id": "h2", "tenant": "t1", "status": "rejected", "created_at": "2023-01-01T04:00:00Z", "decided_at": "2023-01-01T05:00:00Z"},
    ]
    (t1_app / "history.jsonl").write_text("\n".join(json.dumps(r) for r in history_records) + "\n")

    snap = build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)
    t = snap["tenants"][0]
    assert t["approvalCounts"] == {"pending": 2, "approved": 1, "rejected": 1}

    warn_codes = [w["code"] for w in snap["warnings"]]
    assert "approvals_malformed_rows" in warn_codes or "audit_malformed_rows" in warn_codes

    app_activity = snap["activity"]["approvals"]
    assert len(app_activity) == 4
    for item in app_activity:
        assert "token=" not in item["summary"]
        assert "password=" not in item["summary"]

def test_redact_token_and_password_assignments(fixture_repo: Path, tmp_path: Path):
    data_root = tmp_path / "data"
    t1_audit = data_root / "tenants" / "t1" / "audit"
    t1_audit.mkdir(parents=True)

    (t1_audit / "events.jsonl").write_text(
        json.dumps({
            "id": "e_secret",
            "tenant": "t1",
            "agent": "cto token=supersecretpassword123 password=mysecretpass",
            "kind": "event",
            "status": "done"
        }) + "\n"
    )
    snap = build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)
    ev = snap["activity"]["events"][0]
    assert "supersecretpassword123" not in ev["summary"]
    assert "mysecretpass" not in ev["summary"]

def test_document_ancestor_symlink_and_isa_body_denied(fixture_repo: Path, tmp_path: Path):
    # Deny document outside or under ancestor symlink
    symlink_dir = fixture_repo / "docs_symlink"
    try:
        symlink_dir.symlink_to(fixture_repo / "catalog", target_is_directory=True)
        with pytest.raises(Exception):
            read_document(fixture_repo, "docs_symlink/SCHEMA.md")
    except (OSError, NotImplementedError):
        pass

    # ISA.md body direct read via read_document should be denied since ISA.md is not in ALLOWED_DOC_PREFIXES
    with pytest.raises(Exception):
        read_document(fixture_repo, "ISA.md")

def test_isa_checkbox_accepted_and_open_only_noncheckbox_omitted(fixture_repo: Path):
    isa_content = """# Title
Prose mentioning ISC-999 that should be ignored.
| ID | Title | Status |
|---|---|---|
| ISC-000 | Table row non-checkbox | Accepted |

- [x] ISC-1: First criterion accepted
- [ ] ISC-2: Second criterion open
- [X] ISC-3: Third criterion accepted
* [ ] ISC-4: Fourth criterion open
| [x] | ISC-5 | Fifth criterion accepted |
| [ ] | ISC-6 | Sixth criterion open |
"""
    (fixture_repo / "ISA.md").write_text(isa_content)
    snap = build_snapshot(fixture_repo, probe=False)
    acc = snap["acceptance"]

    ids = {item["id"]: item["status"] for item in acc}
    assert ids == {
        "ISC-1": "accepted",
        "ISC-2": "open",
        "ISC-3": "accepted",
        "ISC-4": "open",
        "ISC-5": "accepted",
        "ISC-6": "open",
    }
    assert "ISC-999" not in ids
    assert "ISC-000" not in ids

def test_reads_produce_no_filesystem_writes(fixture_repo: Path, tmp_path: Path):
    data_root = tmp_path / "data"
    t1 = data_root / "tenants" / "t1"
    t1.mkdir(parents=True)

    files_before = set(fixture_repo.rglob("*"))
    data_files_before = set(data_root.rglob("*"))

    _ = build_snapshot(fixture_repo, data_root=data_root, tenant="t1", probe=False)
    _ = read_document(fixture_repo, "README.md")
    _ = preview_plan(fixture_repo, {"tenant": "t1", "title": "Plan", "modules": ["mod-allowed"]}, data_root=data_root)

    files_after = set(fixture_repo.rglob("*"))
    data_files_after = set(data_root.rglob("*"))

    assert files_before == files_after
    assert data_files_before == data_files_after

"""Independent source-parity and isolation checks for the integrated cockpit."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.cockpit_snapshot import build_snapshot, preview_plan, read_document


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value), encoding="utf-8")


def instance(tmp_path: Path, modules: list[str] | None = None) -> Path:
    data = tmp_path / "instance"
    for slug in ("alpha", "beta"):
        write(data / "tenants" / slug / "MANIFEST.yaml", {"name": slug})
        write(data / "tenants" / slug / "runtime.yaml", {"primary": "codex"})
        write(data / "tenants" / slug / "enabled.yaml", {"agents": ["sentinel"], "modules": modules or []})
        write(data / "tenants" / slug / "sources.yaml", {"sources": [{"path": "private-context.md"}]})
    audit = data / "_audit"
    audit.mkdir()
    rows = [
        {"id": "a", "tenant": "alpha", "ts": 123, "agent": "sentinel", "kind": "audit", "summary": "Bearer synthetic-secret-do-not-project", "payload": {"token": "synthetic-secret-do-not-project"}},
        {"id": "b", "tenant": "beta", "ts": 456, "status": "complete"},
        {"id": "u", "ts": 789, "summary": "unscoped record"},
        {"id": "invalid-ts", "tenant": "alpha", "timestamp": "Bearer synthetic-secret-do-not-project"},
        {"id": "iso-ts", "tenant": "alpha", "timestamp": "2026-10-07T19:00:00Z"},
    ]
    (audit / "hermes-events.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return data


def tree_digest(base: Path) -> dict[str, tuple[int, str]]:
    return {str(p.relative_to(base)): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in base.rglob("*") if p.is_file() and not p.is_symlink()}


def test_repository_inventory_and_native_routing_parity():
    snap = build_snapshot(ROOT, probe=False)
    raw = json.loads((ROOT / "catalog/modules.json").read_text())
    for field in ("cards", "agents", "adapters", "connectors"):
        assert snap["catalog"][field] == raw[field]
    hooks = yaml.safe_load((ROOT / "workflows/skill-hooks.yaml").read_text())["routing"]
    expected = {(agent, hook["id"]) for agent, cfg in hooks.items() for hook in cfg.get("hooks", [])}
    actual = {(r["agent"], r["hook"]) for r in snap["routing"]["rules"] if r["source"] == "workflows/skill-hooks.yaml"}
    assert actual == expected and len(actual) > 15
    registry = yaml.safe_load((ROOT / "skills/registry.yaml").read_text())["agents"]
    assert len(snap["routing"]["skills"]) == sum(map(len, registry.values())) == 4
    assert {t["slug"] for t in snap["tenants"]} == {"_demo", "acme", "tryambakam-noesis"}
    assert {n["wing"] for n in snap["fleet"]} == {"coding", "design", "marketing"}
    assert len(snap["acceptance"]) == 107
    assert all(s["state"] == "unknown" and s["checkedAt"] is None for s in snap["services"])


def test_real_hook_preview_matches_source_and_is_never_executable():
    preview = preview_plan(ROOT, {"tenant": "acme", "title": "Refresh GTM brief and brand registration", "modules": []})
    assert any(r["agent"] == "interpreter" and r["hook"] == "gtm-brief-synthesis" and "snowgloves:gtm-brief-synthesis" in r["skills"] for r in preview["routes"])
    assert preview["executable"] is False


def test_scoped_instance_and_ambient_default_are_read_only(tmp_path, monkeypatch):
    data = instance(tmp_path)
    before = tree_digest(data)
    monkeypatch.setenv("SNOWGLOVES_DATA", str(data))
    public = build_snapshot(ROOT, probe=False)
    assert public["scope"]["mode"] == "public-fixtures"
    assert "alpha" not in {t["slug"] for t in public["tenants"]}
    scoped = build_snapshot(ROOT, data_root=data, tenant="alpha", probe=False)
    assert {t["slug"] for t in scoped["tenants"]} == {"alpha"}
    assert all(r["tenant"] == "alpha" for rows in scoped["activity"].values() for r in rows)
    actual_events = {event["id"]: event for event in scoped["activity"]["events"]}
    assert set(actual_events) == {"a", "invalid-ts", "iso-ts"}
    assert actual_events["a"]["timestamp"] == "123"
    assert actual_events["a"]["status"] == "unknown"
    assert actual_events["iso-ts"]["timestamp"] == "2026-10-07T19:00:00Z"
    assert actual_events["invalid-ts"]["timestamp"] is None
    assert "synthetic-secret-do-not-project" not in json.dumps(scoped)
    assert "unscoped record" not in json.dumps(scoped)
    unscoped = build_snapshot(ROOT, data_root=data, probe=False)
    assert not any(unscoped["activity"].values())
    preview_plan(ROOT, {"tenant": "alpha", "title": "Build an architecture proposal", "modules": []}, data_root=data)
    assert tree_digest(data) == before
    with pytest.raises((ValueError, LookupError)):
        build_snapshot(ROOT, data_root=data, tenant="acme", probe=False)


def test_real_catalog_hold_and_high_risk_gates(tmp_path):
    raw = json.loads((ROOT / "catalog/modules.json").read_text())
    held = next(c for c in raw["cards"] if c["disposition"] == "hold")
    refused = next(c for c in raw["cards"] if c["disposition"] == "refuse")
    risky = next(c for c in raw["cards"] if c["disposition"] in ("add", "pointer") and c["risk"] == "high")
    ids = [held["id"], refused["id"], risky["id"]]
    data = instance(tmp_path, ids)
    result = preview_plan(ROOT, {"tenant": "alpha", "title": "Review connector gate", "modules": ids}, data_root=data)
    decisions = {m["id"]: m["decision"] for m in result["modules"]}
    assert decisions[held["id"]] == decisions[refused["id"]] == "refused"
    assert decisions[risky["id"]] == "approval-required"
    assert all(s["status"] == "held" for s in result["steps"])


def test_indexed_documents_return_exact_bounded_source_and_exclude_private(tmp_path):
    doc = read_document(ROOT, "workflows/skill-hooks.yaml")
    assert doc["content"] == (ROOT / doc["path"]).read_text()
    assert doc["sha256"] == hashlib.sha256(doc["content"].encode()).hexdigest()
    for path in ("../README.md", "/etc/passwd", "ISA.md", ".planning/HANDOFF.json", "tenants/acme/MANIFEST.yaml", "https://example.com", "docs/../README.md"):
        with pytest.raises((ValueError, FileNotFoundError)):
            read_document(ROOT, path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").symlink_to(ROOT / "README.md")
    with pytest.raises((ValueError, FileNotFoundError)):
        read_document(repo, "README.md")

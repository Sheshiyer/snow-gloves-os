"""scripts/sg_mods.py: the JSON the Claude Code mods in mods/ read."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import sg_mods  # scripts/ is on sys.path via tests/conftest.py


@pytest.fixture
def data(tmp_path, monkeypatch) -> Path:
    """A private data checkout with one registered tenant and one stray folder."""
    monkeypatch.delenv("SNOWGLOVES_DATA", raising=False)
    monkeypatch.delenv("OMNIROUTE_URL", raising=False)
    root = tmp_path / "ops"
    tenants = root / "tenants"
    (tenants / "acme" / "approvals").mkdir(parents=True)
    (tenants / "stray").mkdir()
    (tenants / "_registry.yaml").write_text("tenants:\n  - acme  # Acme\n", encoding="utf-8")
    (tenants / "acme" / "runtime.yaml").write_text(
        f"preferences:\n  project: {tmp_path / 'work'}\n", encoding="utf-8"
    )
    (tenants / "acme" / "enabled.yaml").write_text(
        "modules:\n  - id: github-mcp\n  - id: xmcp\n  - id: ms-revops\n", encoding="utf-8"
    )
    rows = [
        {"id": "APR-1", "tenant": "acme", "connector": "gmail", "capability": "gmail.send_message",
         "risk": "high", "created_at": 100, "status": "pending", "payload": {"to": "x@y.io"}},
        {"id": "APR-2", "tenant": "acme", "connector": "xmcp", "capability": "post",
         "risk": "high", "created_at": 200, "status": "pending", "payload": {}},
    ]
    (tenants / "acme" / "approvals" / "pending.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows) + "not json\n", encoding="utf-8"
    )
    return root


def history(root: Path, *rows: dict) -> None:
    path = root / "tenants" / "acme" / "approvals" / "history.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_snapshot_flag_tenant_and_payload_keys_only(data, tmp_path):
    out = sg_mods.snapshot(str(data), "acme", tmp_path)
    assert out["schema"] == sg_mods.SCHEMA_SNAPSHOT
    assert out["data_root_source"] == "flag" and out["tenant"] == "acme" and out["tenant_source"] == "flag"
    assert out["approvals"]["pending_total"] == 2 and out["approvals"]["by_tenant"] == {"acme": 2}
    first = out["approvals"]["items"][0]
    assert first["id"] == "APR-2"  # newest first
    gmail = out["approvals"]["items"][1]
    assert gmail["payload_keys"] == ["to"]
    assert "x@y.io" not in json.dumps(out)


def test_snapshot_matches_tenant_by_project(data, tmp_path):
    work = tmp_path / "work" / "sub"
    work.mkdir(parents=True)
    out = sg_mods.snapshot(str(data), None, work)
    assert (out["tenant"], out["tenant_source"]) == ("acme", "project-match")


def test_snapshot_never_assumes_demo(data, tmp_path):
    out = sg_mods.snapshot(str(data), None, tmp_path / "elsewhere")
    assert out["tenant"] is None and out["tenant_source"] == "none"
    assert any("no tenant resolved" in w for w in out["warnings"])


def test_snapshot_env_and_code_fallback(data, tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWGLOVES_DATA", str(data))
    assert sg_mods.snapshot(None, "acme", tmp_path)["data_root_source"] == "env"
    monkeypatch.delenv("SNOWGLOVES_DATA")
    out = sg_mods.snapshot(None, None, tmp_path)
    assert out["data_root_source"] == "code-fallback"
    assert any("SNOWGLOVES_DATA is unset" in w for w in out["warnings"])


def test_snapshot_reads_isa_walk_and_endpoints(data, tmp_path):
    (data / "fleet.yaml").write_text("gateway:\n  url: http://coding-mac:20128/\n", encoding="utf-8")
    out = sg_mods.snapshot(str(data), "acme", tmp_path)
    assert out["isa"]["total"] >= 1 and 0 <= out["isa"]["checked"] <= out["isa"]["total"]
    assert out["walk"] is None or out["walk"]["verdict"] in ("GREEN", "RED", "?")
    assert out["endpoints"] == {"hermes": "http://127.0.0.1:4100", "omniroute": "http://coding-mac:20128"}


def test_bad_slug_is_rejected(data, tmp_path):
    with pytest.raises(sg_mods.InputError):
        sg_mods.snapshot(str(data), "../etc", tmp_path)


def test_gate_table_marks_enabled_and_approval(data):
    out = sg_mods.gate_table(str(data), "acme", 24, now=10_000)
    assert out["schema"] == sg_mods.SCHEMA_GATE
    gh, x = out["servers"]["github-mcp"], out["servers"]["xmcp"]
    assert gh["enabled"] and not gh["needs_approval"]
    assert x["enabled"] and x["needs_approval"]
    assert out["servers"]["lazyweb"]["disposition"] == "hold" and not out["servers"]["lazyweb"]["enabled"]
    assert "ms-revops" not in out["servers"]  # skills are not MCP servers
    assert out["pending"] == [{"connector": "xmcp", "capability": "post", "id": "APR-2"}]


def test_gate_table_grants_respect_ttl(data):
    history(
        data,
        {"id": "old", "connector": "xmcp", "capability": "post", "status": "approved", "decided_at": 1_000},
        {"id": "new", "connector": "xmcp", "capability": "post", "status": "approved", "decided_at": 9_000},
        {"id": "no", "connector": "xmcp", "capability": "post", "status": "rejected", "decided_at": 9_500},
        {"id": "gm", "connector": "gmail", "capability": "x", "status": "approved", "decided_at": 9_500},
    )
    out = sg_mods.gate_table(str(data), "acme", 1, now=10_000)
    assert [g["id"] for g in out["grants"]] == ["new"]


def test_gate_table_unknown_tenant(data):
    with pytest.raises(sg_mods.InputError):
        sg_mods.gate_table(str(data), "nope", 24)


def test_request_approval_queues_then_dedupes(data):
    first = sg_mods.request_approval(str(data), "acme", "xmcp", "search", tool="mcp__xmcp__search")
    assert not first["deduped"]
    ticket = first["ticket"]
    assert ticket["kind"] == "mcp-call" and ticket["risk"] == "high"
    assert ticket["payload"] == {"source": "sg-connector-gate", "tool": "mcp__xmcp__search"}
    again = sg_mods.request_approval(str(data), "acme", "xmcp", "search")
    assert again["deduped"] and again["ticket"]["id"] == ticket["id"]
    pending = (data / "tenants" / "acme" / "approvals" / "pending.jsonl").read_text()
    assert pending.count('"capability": "search"') == 1


def test_request_approval_refuses_unmanaged(data):
    with pytest.raises(sg_mods.InputError):
        sg_mods.request_approval(str(data), "acme", "ms-revops", "x")


def test_cli_prints_json_and_exit_codes(data, tmp_path, capsys):
    assert sg_mods.main(["snapshot", "--data-root", str(data), "--tenant", "acme", "--cwd", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["tenant"] == "acme"
    assert sg_mods.main(["gate-table", "--data-root", str(data), "--tenant", "missing"]) == 2
    assert "unknown tenant" in json.loads(capsys.readouterr().out)["error"]

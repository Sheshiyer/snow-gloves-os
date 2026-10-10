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


# ---------------------------------------------------------------- agents (sg-org)


def test_agents_table_builds_the_seven_subagent_specs(data):
    out = sg_mods.agents_table(str(data), "acme")
    assert out["schema"] == sg_mods.SCHEMA_AGENTS
    slugs = [a["slug"] for a in out["agents"]]
    assert slugs == sorted(["ceo", "cto", "chief-of-staff", "librarian", "interpreter", "dispatcher", "sentinel"])
    cto = next(a for a in out["agents"] if a["slug"] == "cto")
    assert "Chief Technology Agent" in cto["prompt"] and "Escalate to ceo" in cto["prompt"]
    assert cto["escalates_to"] == "ceo" and cto["tools"] == ["Read", "Grep", "Glob", "Bash"] and not cto["readonly"]
    assert "Needs a person's approval for: finance.write" in cto["prompt"]
    assert len(cto["prompt"]) <= sg_mods.MAX_PROMPT


def test_advisory_and_auditing_roles_get_read_only_tools(data):
    by = {a["slug"]: a for a in sg_mods.agents_table(str(data), None)["agents"]}
    for slug in ("sentinel", "librarian", "interpreter", "ceo"):
        assert by[slug]["readonly"] and by[slug]["tools"] == ["Read", "Grep", "Glob"]
        assert "read-only tools" in by[slug]["prompt"]
    assert by["dispatcher"]["tools"][-1] == "Bash" and by["sentinel"]["escalates_to"] == "chief-of-staff"


def test_the_default_skills_and_hooks_come_from_the_registry_and_routing(data):
    by = {a["slug"]: a for a in sg_mods.agents_table(str(data), None)["agents"]}
    assert "snowgloves:connector-gate" in by["sentinel"]["default_skills"]
    assert any(h["id"] == "architecture-and-execution" for h in by["cto"]["hooks"])


def test_an_empty_agents_list_offers_every_role(data):
    out = sg_mods.agents_table(str(data), "acme")
    assert out["restricted"] is False and all(a["enabled"] for a in out["agents"])


def test_a_tenant_that_lists_agents_withholds_the_rest(data):
    (data / "tenants" / "acme" / "enabled.yaml").write_text("agents: [cto, sentinel]\nmodules: []\n", encoding="utf-8")
    out = sg_mods.agents_table(str(data), "acme")
    assert out["restricted"] is True and out["enabled_agents"] == ["cto", "sentinel"]
    assert {a["slug"] for a in out["agents"] if a["enabled"]} == {"cto", "sentinel"}


def test_agents_table_rejects_an_unknown_tenant(data):
    with pytest.raises(sg_mods.InputError):
        sg_mods.agents_table(str(data), "missing")


# ---------------------------------------------------------------- combos (sg-omniroute)


def make_db(path, rows):
    import sqlite3
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE combos (id TEXT, name TEXT, data TEXT)")
    con.execute("CREATE TABLE api_keys (id TEXT, key TEXT)")
    con.execute("INSERT INTO api_keys VALUES ('k', 'sk-secret-should-never-appear')")
    for name, data in rows:
        con.execute("INSERT INTO combos VALUES (?, ?, ?)", (name, name, data if isinstance(data, str) else json.dumps(data)))
    con.commit()
    con.close()


def test_combos_lists_names_strategy_and_members_and_never_a_key(tmp_path):
    db = tmp_path / "storage.sqlite"
    make_db(db, [("noesis-fast", {"strategy": "least-used", "models": [{"model": "a/x"}, {"model": "b/y"}]}),
                 ("noesis-bare", {"models": ["c/z"]}), ("noesis-broken", "{not json")])
    out = sg_mods.combos_table(str(db))
    assert out["schema"] == sg_mods.SCHEMA_COMBOS and out["warnings"] == []
    by = {c["name"]: c for c in out["combos"]}
    assert by["noesis-fast"] == {"name": "noesis-fast", "strategy": "least-used", "members": ["a/x", "b/y"]}
    assert by["noesis-bare"]["members"] == ["c/z"] and by["noesis-broken"]["members"] == []
    assert "sk-secret" not in json.dumps(out)


def test_combos_is_read_only_and_survives_a_missing_database(tmp_path):
    db = tmp_path / "storage.sqlite"
    make_db(db, [("noesis-fast", {"models": []})])
    before = db.read_bytes()
    sg_mods.combos_table(str(db))
    assert db.read_bytes() == before
    gone = sg_mods.combos_table(str(tmp_path / "nope.sqlite"))
    assert gone["combos"] == [] and "no OmniRoute database" in gone["warnings"][0]


# ---------------------------------------------------------------- handoff (sg-handoff)


def test_write_handoff_writes_atomically_and_keeps_a_backup(tmp_path):
    first = sg_mods.write_handoff(str(tmp_path), "Goal: ship\nNext: merge", "s-1")
    target = tmp_path / ".project" / "HANDOFF.md"
    assert first["path"] == str(target) and first["backup"] is None
    text = target.read_text(encoding="utf-8")
    assert "from session s-1" in text and "Goal: ship" in text
    second = sg_mods.write_handoff(str(tmp_path), "Goal: v2")
    assert second["backup"] and "Goal: ship" in open(second["backup"], encoding="utf-8").read()
    assert "Goal: v2" in target.read_text(encoding="utf-8")
    assert not [p for p in (tmp_path / ".project").iterdir() if p.name.startswith(".handoff-")]


@pytest.mark.parametrize("text", ["", "   \n  "])
def test_write_handoff_refuses_empty_text(tmp_path, text):
    with pytest.raises(sg_mods.InputError):
        sg_mods.write_handoff(str(tmp_path), text)


def test_write_handoff_refuses_a_missing_directory_and_huge_text(tmp_path):
    with pytest.raises(sg_mods.InputError):
        sg_mods.write_handoff(str(tmp_path / "nope"), "x")
    with pytest.raises(sg_mods.InputError):
        sg_mods.write_handoff(str(tmp_path), "x" * (sg_mods.MAX_HANDOFF + 1))
    assert not (tmp_path / ".project").exists()


# ---------------------------------------------------------------- intake (sg-catalog)


def report(hooks, calls, env_reads=None):
    notes = [f"./register.ts hooks: {', '.join(hooks)}", f"./register.ts calls: {', '.join(calls)}"]
    if env_reads:
        notes.append(f"./register.ts env reads: {', '.join(env_reads)}")
    return {"success": True, "contents": [{"notes": notes, "errors": []}]}


def test_draft_card_writes_a_hold_card_and_flags_rule_breakers(tmp_path):
    rep = report(["tool.check", "session.start"], ["$.process.spawn", "$.http.fetch", "$.ui.toast"], ["HOME"])
    out = sg_mods.draft_card("acme-redactor", "claudemod.com/secret-redactor", rep, "Secret Redactor", tmp_path)
    assert out["disposition"] == "hold" and out["flags"] == ["I1", "I5", "I6"]
    card = (tmp_path / "acme-redactor.md").read_text(encoding="utf-8")
    assert "disposition: hold" in card and "category: mod" in card and "risk: high" in card and "approval: yes" in card
    assert "- I1:" in card and "- I6:" in card and "- env reads: HOME" in card and "$.process.spawn" in card


def test_draft_card_for_a_clean_mod_flags_nothing_but_stays_on_hold(tmp_path):
    out = sg_mods.draft_card("tidy", "claudemod.com/tidy", report(["session.start"], ["$.ui.toast"]), None, tmp_path)
    assert out["flags"] == [] and "disposition: hold" in (tmp_path / "tidy.md").read_text(encoding="utf-8")
    assert "- none flagged" in (tmp_path / "tidy.md").read_text(encoding="utf-8")


def test_draft_card_refuses_bad_ids_overwrites_and_non_reports(tmp_path):
    rep = report(["session.start"], ["$.ui.toast"])
    for bad in ("", "Bad Id", "../x", "x"):
        with pytest.raises(sg_mods.InputError):
            sg_mods.draft_card(bad, "src", rep, None, tmp_path)
    sg_mods.draft_card("once", "src", rep, None, tmp_path)
    with pytest.raises(sg_mods.InputError):
        sg_mods.draft_card("once", "src", rep, None, tmp_path)
    with pytest.raises(sg_mods.InputError):
        sg_mods.draft_card("other", "src", {"nope": 1}, None, tmp_path)


def test_a_drafted_card_is_a_hold_card_the_catalog_builder_accepts(tmp_path):
    import build_catalog
    sg_mods.draft_card("probe-mod", "claudemod.com/probe", report(["session.start"], ["$.ui.toast"]), "Probe", tmp_path)
    meta = build_catalog.parse_card(tmp_path / "probe-mod.md") if hasattr(build_catalog, "parse_card") else None
    text = (tmp_path / "probe-mod.md").read_text(encoding="utf-8")
    assert text.startswith("---\nid: probe-mod\n") and "disposition: hold" in text
    assert meta is None or meta["disposition"] == "hold"


def test_cli_new_subcommands_print_json(data, tmp_path, capsys, monkeypatch):
    assert sg_mods.main(["agents", "--data-root", str(data), "--tenant", "acme"]) == 0
    assert len(json.loads(capsys.readouterr().out)["agents"]) == 7
    assert sg_mods.main(["combos", "--db", str(tmp_path / "none.sqlite")]) == 0
    assert json.loads(capsys.readouterr().out)["combos"] == []
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("Goal: x"))
    assert sg_mods.main(["write-handoff", "--cwd", str(tmp_path), "--session", "s"]) == 0
    assert json.loads(capsys.readouterr().out)["path"].endswith(".project/HANDOFF.md")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert sg_mods.main(["write-handoff", "--cwd", str(tmp_path)]) == 2
    assert "empty" in json.loads(capsys.readouterr().out)["error"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(report(["session.start"], ["$.ui.toast"]))))
    assert sg_mods.main(["draft-card", "--id", "cli-card", "--source", "src", "--cards-dir", str(tmp_path / "cards")]) == 0
    assert json.loads(capsys.readouterr().out)["disposition"] == "hold"
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert sg_mods.main(["draft-card", "--id", "cli-2", "--source", "src", "--cards-dir", str(tmp_path / "cards")]) == 2


def test_catalog_table_lists_cards_without_bodies_and_the_tenants_enabled_ids(data):
    out = sg_mods.catalog_table(str(data), "acme")
    assert out["schema"] == "snowgloves.mods-catalog.v1"
    assert out["enabled"] == ["github-mcp", "ms-revops", "xmcp"]
    assert out["cards"] and all("body" not in card for card in out["cards"])
    ids = {card["id"] for card in out["cards"]}
    assert {"sg-approvals", "sg-rail"} <= ids


def test_catalog_table_without_a_tenant_enables_nothing(data):
    assert sg_mods.catalog_table(str(data), None)["enabled"] == []


def test_catalog_table_unknown_tenant(data):
    with pytest.raises(sg_mods.InputError):
        sg_mods.catalog_table(str(data), "nobody")


def test_add_card_ids_lists_only_mod_cards_marked_add():
    ids = sg_mods.add_card_ids(sg_mods.paths.code_root())
    assert "sg-approvals" in ids and "agent-reach" not in ids

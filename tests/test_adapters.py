import json
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import adapters as ad

ADAPTERS = ROOT / "adapters"
EXPECTED = {"hermes", "claude", "codex", "cursor", "opencode", "grok", "openclaw", "muse", "generic"}


def test_every_expected_runtime_ships_an_adapter():
    assert EXPECTED <= set(ad.list_adapters(ADAPTERS))


@pytest.mark.parametrize("runtime", sorted(EXPECTED))
def test_adapter_is_valid_schema_v1(runtime):
    data = yaml.safe_load((ADAPTERS / runtime / "adapter.yaml").read_text())
    assert ad.validate(data, runtime) == []
    assert ad.load_adapter(ADAPTERS, runtime)["id"] == runtime


def test_question_tools_match_runtime_conventions():
    tools = {rt: ad.load_adapter(ADAPTERS, rt)["question_tool"] for rt in EXPECTED}
    assert tools["cursor"] == "AskQuestion"
    assert tools["claude"] == "AskUserQuestion"
    assert tools["codex"] == "request_user_input"
    assert tools["generic"] == ad.FALLBACK_QUESTION_TOOL


def test_verify_marks_are_field_names_that_exist():
    for rt in EXPECTED:
        data = ad.load_adapter(ADAPTERS, rt)
        for dotted in ad.verify_fields(data):
            node = data
            for part in dotted.split("."):
                node = node[int(part)] if isinstance(node, list) else node[part]


def test_validate_catches_bad_adapter():
    problems = ad.validate({"schema": "x", "id": "a", "paths": {}, "formats": {}}, "b")
    text = " ".join(problems)
    assert "schema must be" in text and "does not match folder" in text and "paths.skills" in text


def test_unknown_runtime_raises_with_known_list(tmp_path):
    with pytest.raises(ad.AdapterError, match="known:"):
        ad.load_adapter(ADAPTERS, "nope")


def test_adding_a_runtime_is_adding_a_folder(tmp_path):
    folder = tmp_path / "newrt"
    folder.mkdir()
    base = yaml.safe_load((ADAPTERS / "generic" / "adapter.yaml").read_text())
    base["id"] = "newrt"
    (folder / "adapter.yaml").write_text(yaml.safe_dump(base))
    assert ad.list_adapters(tmp_path) == ["newrt"]
    assert ad.load_adapter(tmp_path, "newrt")["name"]


def test_resolve_templates():
    roots = {"home": Path("/h"), "project": Path("/p"), "tenant": Path("/t")}
    assert ad.resolve("{home}/.claude/skills", roots) == Path("/h/.claude/skills")
    assert ad.resolve(None, roots) is None


def test_upsert_block_is_idempotent_and_keeps_user_text():
    once = ad.upsert_block("# Mine\n\nkeep me\n", "v1")
    twice = ad.upsert_block(once, "v2")
    assert "keep me" in twice and "v2" in twice and "v1" not in twice
    assert twice.count(ad.BLOCK_START) == 1


ITEMS = [
    {"id": "sk", "name": "Sk", "category": "skills", "disposition": "add", "summary": "a skill", "risk": "low"},
    {"id": "srv", "name": "Srv", "category": "mcp", "disposition": "add", "risk": "high",
     "mcp": {"command": "npx", "args": ["srv"]}},
    {"id": "pl", "name": "Pl", "category": "plugin", "disposition": "add", "repo": "o/r"},
    {"id": "ptr", "name": "Ptr", "category": "playbook", "disposition": "pointer"},
]


def _roots(tmp_path):
    return {"home": tmp_path / "home", "project": tmp_path / "project", "tenant": tmp_path / "tenant"}


def test_render_claude_json_merges_existing_servers(tmp_path):
    roots = _roots(tmp_path)
    mcp = roots["project"] / ".mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text(json.dumps({"mcpServers": {"old": {"command": "x"}}}))
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "claude"), ITEMS, ["ceo"], "t1", roots)
    ad.write_plan(plan)
    data = json.loads(mcp.read_text())
    assert set(data["mcpServers"]) == {"old", "srv"}
    skill = (roots["home"] / ".claude" / "skills" / "sk" / "SKILL.md").read_text()
    assert skill.startswith("---\nname: sk\n")
    assert not (roots["home"] / ".claude" / "skills" / "ptr").exists()
    assert any("ptr" in s for s in plan.skipped)


def test_render_codex_appends_toml_without_rewriting(tmp_path):
    roots = _roots(tmp_path)
    cfg = roots["home"] / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('model = "x"\n\n[mcp_servers.srv]\ncommand = "keep"\n')
    items = ITEMS + [{"id": "srv2", "category": "mcp", "disposition": "add"}]
    ad.write_plan(ad.render_plan(ad.load_adapter(ADAPTERS, "codex"), items, [], "t1", roots))
    data = tomllib.loads(cfg.read_text())
    assert data["model"] == "x"
    assert data["mcp_servers"]["srv"]["command"] == "keep"
    assert data["mcp_servers"]["srv2"]["command"].startswith("FILL:")


def test_render_opencode_uses_command_array(tmp_path):
    roots = _roots(tmp_path)
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "opencode"), ITEMS, [], "t1", roots)
    ad.write_plan(plan)
    data = json.loads((roots["home"] / ".config" / "opencode" / "opencode.json").read_text())
    assert data["mcp"]["srv"] == {"type": "local", "command": ["npx", "srv"], "enabled": True}


def test_render_hermes_never_rewrites_existing_yaml_config(tmp_path):
    roots = _roots(tmp_path)
    cfg = roots["home"] / ".hermes" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("# secrets here\nmcp_servers: {}\n")
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "hermes"), ITEMS, [], "t1", roots)
    ad.write_plan(plan)
    assert cfg.read_text() == "# secrets here\nmcp_servers: {}\n"
    assert (cfg.parent / "config.snowgloves.yaml").is_file()
    skill = (roots["home"] / ".hermes" / "skills" / "sk" / "SKILL.md").read_text()
    assert "hermes:" in skill


def test_render_cursor_writes_mdc_rule_and_plugin_note(tmp_path):
    roots = _roots(tmp_path)
    ad.write_plan(ad.render_plan(ad.load_adapter(ADAPTERS, "cursor"), ITEMS, ["cto"], "t1", roots))
    rule = (roots["project"] / ".cursor" / "rules" / "snowgloves.mdc").read_text()
    assert "alwaysApply: true" in rule and "cto" in rule
    assert "pl" in (roots["tenant"] / "runtime" / "cursor" / "plugins.md").read_text()
    manifest = json.loads((roots["tenant"] / "runtime" / "cursor" / "render.json").read_text())
    assert manifest["runtime"] == "cursor"


def test_upsert_block_tagged_keeps_both_tenants_and_migrates_legacy():
    legacy = ad.upsert_block("# Mine\n\nkeep me\n", "old body")
    assert ad.BLOCK_START in legacy
    migrated = ad.upsert_block(legacy, "acme body", tag="acme")
    assert ad.BLOCK_START not in migrated and "old body" not in migrated
    assert "<!-- snowgloves:start tenant=acme -->" in migrated and "keep me" in migrated
    both = ad.upsert_block(migrated, "bakery body", tag="bakery")
    assert "acme body" in both and "bakery body" in both
    again = ad.upsert_block(both, "acme v2", tag="acme")
    assert "acme v2" in again and "acme body" not in again and "bakery body" in again
    assert again.count("snowgloves:start") == 2 and again.count("snowgloves:end") == 2
    # a tag that is a prefix of another tag does not match it
    prefixed = ad.upsert_block(both, "acme-2 body", tag="acme-2")
    assert prefixed.count("snowgloves:start") == 3
    # the untagged path is unchanged
    assert ad.upsert_block(None, "x") == f"{ad.BLOCK_START}\nx\n{ad.BLOCK_END}\n"
    assert ad.upsert_block("", "x", tag=None) == f"{ad.BLOCK_START}\nx\n{ad.BLOCK_END}\n"


def test_render_opencode_keeps_env_as_environment_and_honours_node_override(tmp_path):
    roots = _roots(tmp_path)
    items = ITEMS + [{"id": "envsrv", "name": "Env", "category": "mcp", "disposition": "add", "risk": "low",
                      "mcp": {"command": "npx", "args": ["e"], "env": {"TOKEN": "${TOKEN}"}}}]
    node = {"wing": "coding", "mcps": {"srv": {"command": "uvx", "args": ["srv2"]}}}
    links = [Path("/abs/tenant/context/voice.md")]
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "opencode"), items, [], "t1", roots, node=node, context_links=links)
    ad.write_plan(plan)
    data = json.loads((roots["home"] / ".config" / "opencode" / "opencode.json").read_text())
    assert data["mcp"]["envsrv"] == {"type": "local", "command": ["npx", "e"], "enabled": True,
                                     "environment": {"TOKEN": "${TOKEN}"}}
    assert data["mcp"]["srv"] == {"type": "local", "command": ["uvx", "srv2"], "enabled": True}
    rules = (roots["project"] / "AGENTS.md").read_text()
    assert "Wing:" in rules and "coding" in rules and "tenant=t1" in rules
    assert "Brand context" in rules and "/abs/tenant/context/voice.md" in rules
    manifest = json.loads((roots["tenant"] / "runtime" / "coding" / "opencode" / "render.json").read_text())
    assert manifest["wing"] == "coding" and manifest["effective"] == [i["id"] for i in items]
    assert not (roots["tenant"] / "runtime" / "opencode").exists()


def test_render_without_node_is_unchanged(tmp_path):
    roots = _roots(tmp_path)
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "opencode"), ITEMS, [], "t1", roots)
    ad.write_plan(plan)
    manifest = json.loads((roots["tenant"] / "runtime" / "opencode" / "render.json").read_text())
    assert "wing" not in manifest and "effective" not in manifest
    rules = (roots["project"] / "AGENTS.md").read_text()
    assert rules.startswith(ad.BLOCK_START) and "Wing:" not in rules and "tenant=" not in rules


MODS = [
    {"id": "sg-rail", "name": "Rail", "category": "mod", "disposition": "add"},
    {"id": "sg-approvals", "name": "Approvals", "category": "mod", "disposition": "add"},
    {"id": "sg-nope", "name": "Nope", "category": "mod", "disposition": "add"},
]


def test_render_claude_mods_writes_a_settings_fragment(tmp_path):
    roots = {**_roots(tmp_path), "platform": ROOT}
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "claude"), MODS, [], "acme", roots, data_root=tmp_path / "ops")
    ad.write_plan(plan)
    fragment = json.loads((roots["tenant"] / "runtime" / "claude" / "mods.settings.json").read_text())
    market = fragment["extraKnownMarketplaces"]["snowgloves-mods"]["source"]
    assert market == {"source": "directory", "path": str(ROOT / "mods")}
    assert fragment["enabledPlugins"] == {"sg-rail@snowgloves-mods": True, "sg-approvals@snowgloves-mods": True}
    configs = fragment["pluginConfigs"]
    assert configs["sg-rail@snowgloves-mods"]["options"] == {"tenant": "acme", "dataRoot": str(tmp_path / "ops")}
    assert configs["sg-approvals@snowgloves-mods"]["options"] == {"dataRoot": str(tmp_path / "ops")}  # no tenant option
    assert any(s.startswith("sg-nope: not listed") for s in plan.skipped)
    assert "claude plugin install sg-rail@snowgloves-mods" in (roots["tenant"] / "runtime" / "claude" / "plugins.md").read_text()
    assert not (roots["home"] / ".claude" / "settings.json").exists()


def test_render_claude_mods_without_data_root_leaves_it_out(tmp_path):
    roots = {**_roots(tmp_path), "platform": ROOT}
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "claude"), MODS[:1], [], "acme", roots)
    fragment = json.loads(plan.files[roots["tenant"] / "runtime" / "claude" / "mods.settings.json"])
    assert fragment["pluginConfigs"]["sg-rail@snowgloves-mods"]["options"] == {"tenant": "acme"}


def test_render_mods_on_other_runtimes_is_skipped(tmp_path):
    roots = {**_roots(tmp_path), "platform": ROOT}
    plan = ad.render_plan(ad.load_adapter(ADAPTERS, "cursor"), MODS[:1], [], "acme", roots)
    assert any("no mod support" in s for s in plan.skipped)
    assert not any(p.name == "mods.settings.json" for p in plan.files)


def test_validate_wants_a_mods_format_with_a_mods_path():
    data = yaml.safe_load((ADAPTERS / "claude" / "adapter.yaml").read_text())
    del data["formats"]["mods"]
    assert any("formats.mods" in p for p in ad.validate(data, "claude"))

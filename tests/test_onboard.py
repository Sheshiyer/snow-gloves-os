import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import onboard

MODULES = {
    "schema": "snowgloves.modules.v1",
    "version": "0.2.0",
    "agents": [{"slug": "ceo", "role": "Chief Executive Agent"}, {"slug": "interpreter", "role": "Interpreter"}],
    "cards": [
        {"id": "ms-copywriting", "name": "Copywriting", "category": "skills", "kind": "skill", "disposition": "add",
         "repo": "https://github.com/x/y", "source": "1", "risk": "low", "approval": "no",
         "agents": ["interpreter"], "runtimes": ["any"], "summary": "Write page copy.", "body": "# Copywriting\n\nBody."},
        {"id": "xmcp", "name": "X MCP", "category": "mcp", "kind": "mcp-server", "disposition": "add",
         "repo": "https://github.com/x/xmcp", "source": "2", "risk": "high", "approval": "yes",
         "agents": ["dispatcher"], "runtimes": ["any"], "summary": "X platform MCP."},
        {"id": "fk-payments", "name": "Payments", "category": "playbook", "kind": "resource-list",
         "disposition": "pointer", "repo": "", "source": "", "risk": "low", "approval": "no",
         "agents": ["ceo"], "runtimes": ["any"], "summary": "Pointer."},
        {"id": "openspec", "name": "OpenSpec", "category": "skills", "kind": "skill-pack", "disposition": "hold",
         "repo": "", "source": "", "risk": "low", "approval": "no", "agents": [], "runtimes": ["any"], "summary": "Held."},
        {"id": "claude-mem", "name": "claude-mem", "category": "plugin", "kind": "memory-plane", "disposition": "refuse",
         "repo": "", "source": "", "risk": "low", "approval": "no", "agents": [], "runtimes": ["any"], "summary": "Refused."},
    ],
    "adapters": [],
    "connectors": [{"id": "explee_proxy", "auth": "api_key",
                    "capabilities": [{"id": "explee.autogtm", "risk": "high", "approval": "yes"}]}],
}

HARVEST = """## Tenant

slug: bakery
name: The Bakery

## Owner

Ana decides. Never send email without asking.

## Company

A neighbourhood bakery.

## Customer

FILL: who buys, in their words

## Offer

Sourdough, 6 EUR (menu.md).

## Voice

Warm, short.

## Proof

No approved claims yet.

## Agents

- interpreter
- ceo

## Skills

- ms-copywriting: first job
- fk-payments

## Connectors

- xmcp
- explee_proxy

## Runtimes

- cursor: primary
- codex

## Preferences

approval_mode: ask-on-send
render: dry-run

## Sources

- /tmp/bakery-docs

## Open questions

- FILL: who buys, in their words
"""


@pytest.fixture
def root(tmp_path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "modules.json").write_text(json.dumps(MODULES))
    (tmp_path / "tenants").mkdir()
    (tmp_path / "tenants" / "_registry.yaml").write_text("tenants:\n  - acme  # Acme Co\n")
    return tmp_path


def run(root, *args):
    return onboard.main(["--root", str(root), *args])


def harvest_file(tmp_path, text=HARVEST):
    path = tmp_path / "snowgloves-harvest.md"
    path.write_text(text)
    return path


def test_steps_lists_runtimes(root, capsys):
    assert run(root, "--steps") == 0
    out = capsys.readouterr().out
    assert "--prompt <runtime>" in out and "cursor" in out and "hermes" in out


def test_prompt_uses_runtime_question_tool_and_catalog_options(root, capsys):
    run(root, "--prompt", "cursor")
    out = capsys.readouterr().out
    assert "{{" not in out
    assert "`AskQuestion`" in out and "Plan mode" in out
    assert "`ms-copywriting`" in out and "`xmcp`" in out and "`explee_proxy`" in out
    offered, blocked = out.split("### Not offered")
    assert "`openspec`" not in offered and "`openspec` — hold" in blocked
    assert "FILL:" in out and "snowgloves-harvest.md" in out
    for heading in ("## Tenant", "## Agents", "## Skills", "## Connectors", "## Runtimes", "## Open questions"):
        assert heading in out


def test_prompt_falls_back_to_numbered_list(root, capsys):
    run(root, "--prompt", "openclaw")
    out = capsys.readouterr().out
    assert "`numbered-list`" in out and "no plan mode" in out


def test_prompt_without_catalog_says_so(tmp_path, capsys):
    onboard.main(["--root", str(tmp_path), "--prompt", "claude"])
    out = capsys.readouterr().out
    assert "not built yet" in out and "AskUserQuestion" in out


def test_apply_harvest_writes_tenant(root, tmp_path):
    assert run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery") == 0
    t = root / "tenants" / "bakery"
    assert "Ana decides" in (t / "context" / "owner.md").read_text()
    assert "FILL:" in (t / "context" / "customer.md").read_text()
    assert "FILL:" in (t / "context" / "open-questions.md").read_text()
    assert (t / "raw" / "harvest.md").read_text() == HARVEST
    enabled = yaml.safe_load((t / "enabled.yaml").read_text())
    assert enabled["agents"] == ["interpreter", "ceo"]
    assert [m["id"] for m in enabled["modules"]] == ["ms-copywriting", "fk-payments", "xmcp", "explee_proxy"]
    rt = yaml.safe_load((t / "runtime.yaml").read_text())
    assert rt["primary"] == "cursor" and [r["id"] for r in rt["runtimes"]] == ["cursor", "codex"]
    assert rt["preferences"]["approval_mode"] == "ask-on-send"
    assert yaml.safe_load((t / "sources.yaml").read_text())["sources"][0]["path"] == "/tmp/bakery-docs"
    assert "bakery" in (root / "tenants" / "_registry.yaml").read_text()
    assert "business_name" in (t / "MANIFEST.yaml").read_text()


def test_apply_harvest_keeps_existing_tenant_files(root, tmp_path):
    t = root / "tenants" / "bakery"
    t.mkdir()
    (t / "MANIFEST.yaml").write_text("tenant: bakery\n# mine\n")
    (t / "sources.yaml").write_text("tenant: bakery\nsources: []  # mine\n")
    run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery")
    assert (t / "MANIFEST.yaml").read_text() == "tenant: bakery\n# mine\n"
    assert "# mine" in (t / "sources.yaml").read_text()
    registry = (root / "tenants" / "_registry.yaml").read_text()
    run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery")
    assert (root / "tenants" / "_registry.yaml").read_text() == registry


def test_apply_harvest_refuses_hold_before_writing(root, tmp_path):
    text = HARVEST.replace("- fk-payments", "- openspec")
    with pytest.raises(SystemExit, match="openspec is on hold"):
        run(root, "--apply-harvest", str(harvest_file(tmp_path, text)), "--tenant", "bakery")
    assert not (root / "tenants" / "bakery").exists()


def test_apply_harvest_rejects_missing_headings_and_slug_mismatch(root, tmp_path):
    with pytest.raises(SystemExit, match="missing headings"):
        run(root, "--apply-harvest", str(harvest_file(tmp_path, "## Owner\n\nx\n")), "--tenant", "bakery")
    with pytest.raises(SystemExit, match="names tenant 'bakery'"):
        run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "other")


def test_apply_harvest_rejects_unknown_runtime(root, tmp_path):
    text = HARVEST.replace("- codex", "- vscode")
    with pytest.raises(SystemExit, match="unknown runtime"):
        run(root, "--apply-harvest", str(harvest_file(tmp_path, text)), "--tenant", "bakery")


def test_enable_is_additive_and_refuses_hold_and_refuse(root, tmp_path):
    run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery")
    with pytest.raises(SystemExit) as err:
        run(root, "--enable", "openspec,claude-mem", "--tenant", "bakery")
    assert "openspec is on hold" in str(err.value) and "claude-mem is refused" in str(err.value)
    with pytest.raises(SystemExit, match="unknown id"):
        run(root, "--enable", "nope", "--tenant", "bakery")
    run(root, "--replace", "--enable", "xmcp", "--tenant", "bakery")
    enabled = yaml.safe_load((root / "tenants" / "bakery" / "enabled.yaml").read_text())
    assert [m["id"] for m in enabled["modules"]] == ["xmcp"]
    run(root, "--enable", "ms-copywriting", "--tenant", "bakery")
    enabled = yaml.safe_load((root / "tenants" / "bakery" / "enabled.yaml").read_text())
    assert [m["id"] for m in enabled["modules"]] == ["xmcp", "ms-copywriting"]


def test_enable_needs_existing_tenant(root):
    with pytest.raises(SystemExit, match="no such tenant"):
        run(root, "--enable", "xmcp", "--tenant", "ghost")


def test_render_dry_run_writes_nothing(root, tmp_path, capsys):
    run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery")
    out_dir = tmp_path / "out"
    run(root, "--render-adapter", "claude", "--tenant", "bakery", "--out", str(out_dir))
    out = capsys.readouterr().out
    assert "would write" in out and "nothing written" in out
    assert not out_dir.exists()


@pytest.mark.parametrize("runtime,skill,mcp", [
    ("claude", "home/.claude/skills/ms-copywriting/SKILL.md", "project/.mcp.json"),
    ("codex", "home/.codex/skills/ms-copywriting/SKILL.md", "home/.codex/config.toml"),
    ("cursor", "home/.cursor/skills/ms-copywriting/SKILL.md", "project/.cursor/mcp.json"),
    ("grok", "home/.grok/skills/ms-copywriting/SKILL.md", "home/.grok/config.toml"),
    ("generic", "tenant/runtime/generic/skills/ms-copywriting/SKILL.md", "tenant/runtime/generic/mcp.json"),
])
def test_render_write_emits_only_enabled_items(root, tmp_path, runtime, skill, mcp):
    run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery")
    out_dir = tmp_path / "out"
    run(root, "--render-adapter", runtime, "--tenant", "bakery", "--out", str(out_dir), "--write")
    skill_text = (out_dir / skill).read_text()
    assert "Body." in skill_text and "bakery" in skill_text
    mcp_text = (out_dir / mcp).read_text()
    assert "xmcp" in mcp_text and "explee_proxy" not in mcp_text
    rendered = {p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file()}
    assert not any("openspec" in p or "claude-mem" in p or "fk-payments" in p for p in rendered)
    manifest = json.loads((out_dir / "tenant" / "runtime" / runtime / "render.json").read_text())
    assert manifest["tenant"] == "bakery"


def test_render_project_defaults_to_tenant_not_cwd(root, tmp_path, capsys):
    run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery")
    run(root, "--render-adapter", "claude", "--tenant", "bakery")
    out = capsys.readouterr().out
    assert f"{root / 'tenants' / 'bakery' / '.mcp.json'}" in out
    assert not (root / "tenants" / "bakery" / ".mcp.json").exists()


def test_render_skips_card_that_moved_to_hold(root, tmp_path, capsys):
    run(root, "--apply-harvest", str(harvest_file(tmp_path)), "--tenant", "bakery")
    data = json.loads((root / "catalog" / "modules.json").read_text())
    data["cards"][0]["disposition"] = "hold"
    (root / "catalog" / "modules.json").write_text(json.dumps(data))
    out_dir = tmp_path / "out"
    run(root, "--render-adapter", "claude", "--tenant", "bakery", "--out", str(out_dir), "--write")
    assert "skip ms-copywriting is on hold" in capsys.readouterr().err
    assert not (out_dir / "home" / ".claude" / "skills" / "ms-copywriting").exists()


def test_list_groups_by_disposition_and_filters_category(root, capsys):
    run(root, "--list")
    out = capsys.readouterr().out
    assert "OFFERED" in out and "ON HOLD" in out and "REFUSED" in out and "POINTER" in out
    run(root, "--list", "--category", "mcp")
    out = capsys.readouterr().out
    assert "xmcp" in out and "ms-copywriting" not in out
    run(root, "--list", "--json", "--category", "skills")
    ids = [c["id"] for c in json.loads(capsys.readouterr().out)]
    assert ids == ["ms-copywriting", "openspec"]


def test_list_without_catalog(tmp_path, capsys):
    onboard.main(["--root", str(tmp_path), "--list"])
    assert "build_catalog.py" in capsys.readouterr().out


def test_commands_need_tenant(root):
    with pytest.raises(SystemExit, match="need --tenant"):
        run(root, "--enable", "xmcp")
    with pytest.raises(SystemExit, match="bad tenant slug"):
        run(root, "--enable", "xmcp", "--tenant", "Bad Slug")


def test_init_tenant_matches_legacy_sources_yaml(root, monkeypatch):
    answers = iter(["The Bakery", "bakery", "/docs/a", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    monkeypatch.setenv("HERMES_PORT", "4100")
    assert run(root, "--init-tenant") == 0
    data = yaml.safe_load((root / "tenants" / "bakery" / "sources.yaml").read_text())
    assert data["business_name"] == "The Bakery" and data["hermes"]["port"] == 4100
    assert data["sources"] == [{"path": "/docs/a", "kind": "auto", "ingest": True}]

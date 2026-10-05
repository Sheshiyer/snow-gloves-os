import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "fleet"))
import onboard  # noqa: E402
import node_profile as np  # noqa: E402

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
         "agents": [], "runtimes": ["any"], "summary": "X platform MCP."},
        {"id": "fk-payments", "name": "Payments", "category": "playbook", "kind": "resource-list",
         "disposition": "pointer", "repo": "", "source": "", "risk": "low", "approval": "no",
         "agents": ["ceo"], "runtimes": ["any"], "summary": "Pointer."},
        {"id": "openspec", "name": "OpenSpec", "category": "skills", "kind": "skill-pack", "disposition": "hold",
         "repo": "", "source": "", "risk": "low", "approval": "no", "agents": [], "runtimes": ["any"], "summary": "Held."},
    ],
    "adapters": [],
    "connectors": [{"id": "explee_proxy", "auth": "api_key",
                    "capabilities": [{"id": "explee.autogtm", "risk": "high", "approval": "yes"}]}],
}

NODE = {
    "schema": "snowgloves.node.v1",
    "wing": "coding",
    "hostname": "coding-mac",
    "operator_user": "sg-coding",
    "primary": "claude",
    "runtimes": ["claude", "codex", "opencode"],
    "modules": ["ms-copywriting", "xmcp"],
    "mcps": {"xmcp": {"command": "npx", "args": ["-y", "xmcp"], "env": {"X_BEARER": "${X_BEARER}"}}},
    "connectors": [],
    "tenants": "all",
}

HARVEST = """## Tenant

slug: bakery
name: The Bakery

## Owner

Ana decides.

## Company

A neighbourhood bakery.

## Customer

FILL: who buys, in their words

## Offer

Sourdough, 6 EUR.

## Voice

Warm, short.

## Proof

No approved claims yet.

## Agents

- interpreter

## Skills

- ms-copywriting
- fk-payments

## Connectors

- xmcp
- explee_proxy

## Runtimes

- cursor: primary
- claude

## Preferences

render: dry-run

## Sources

- /tmp/bakery-docs

## Open questions

- FILL: who buys, in their words
"""


def write_node(root, data=NODE):
    folder = root / "nodes" / data["wing"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "node.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


@pytest.fixture
def root(tmp_path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "modules.json").write_text(json.dumps(MODULES))
    (tmp_path / "tenants").mkdir()
    (tmp_path / "tenants" / "_registry.yaml").write_text("tenants:\n  - acme  # Acme Co (no folder yet)\n")
    write_node(tmp_path)
    harvest = tmp_path / "snowgloves-harvest.md"
    harvest.write_text(HARVEST)
    onboard.main(["--root", str(tmp_path), "--apply-harvest", str(harvest), "--tenant", "bakery"])
    return tmp_path


def run(root, *args):
    return np.main(["--root", str(root), *args])


def enabled_ids(root, slug="bakery"):
    data = yaml.safe_load((root / "tenants" / slug / "enabled.yaml").read_text())
    return [m["id"] for m in data["modules"]]


def test_list_shows_wings_with_status(root, capsys):
    assert run(root, "list") == 0
    out = capsys.readouterr().out
    assert "coding" in out and "coding-mac" in out and "ok" in out


def test_show_prints_yaml_and_validation(root, capsys):
    assert run(root, "show", "coding") == 0
    out = capsys.readouterr().out
    assert "wing: coding" in out and "modules:" in out and "valid" in out
    assert run(root, "show", "design") == 1
    assert "known: coding" in capsys.readouterr().err


def test_show_and_render_exit_2_on_invalid_node(root, capsys):
    write_node(root, {**NODE, "modules": ["ms-copywriting", "openspec"]})
    assert run(root, "show", "coding") == 2
    assert "openspec is on hold" in capsys.readouterr().err
    assert run(root, "render", "--tenant", "bakery", "--node", "coding", "--runtime", "claude") == 2
    write_node(root, {**NODE, "wing": "design"})
    (root / "nodes" / "coding" / "node.yaml").write_text(yaml.safe_dump({**NODE, "wing": "design"}))
    assert run(root, "show", "coding") == 2
    assert "does not match folder" in capsys.readouterr().err


def test_render_refuses_runtime_not_in_node(root, tmp_path, capsys):
    rc = run(root, "render", "--tenant", "bakery", "--node", "coding", "--runtime", "cursor", "--out", str(tmp_path / "out"))
    assert rc == 1
    err = capsys.readouterr().err
    assert "cursor" in err and "coding" in err
    assert not (tmp_path / "out").exists()


def test_render_refuses_tenant_not_served(root, tmp_path, capsys):
    write_node(root, {**NODE, "tenants": [{"slug": "other"}]})
    rc = run(root, "render", "--tenant", "bakery", "--node", "coding", "--runtime", "claude", "--out", str(tmp_path / "out"))
    assert rc == 1
    assert "not served" in capsys.readouterr().err


def test_render_intersects_and_writes_manifest_under_wing(root, tmp_path, capsys):
    out = tmp_path / "out"
    assert run(root, "render", "--tenant", "bakery", "--node", "coding", "--runtime", "claude", "--out", str(out), "--write") == 0
    captured = capsys.readouterr()
    assert "skip fk-payments: not in wing profile coding" in captured.err
    assert "skip explee_proxy: not in wing profile coding" in captured.err
    manifest_path = out / "tenant" / "runtime" / "coding" / "claude" / "render.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["wing"] == "coding"
    assert manifest["effective"] == ["ms-copywriting", "xmcp"]
    assert manifest["tenant"] == "bakery" and manifest["runtime"] == "claude"
    assert not (out / "tenant" / "runtime" / "claude").exists()
    assert (out / "home" / ".claude" / "skills" / "ms-copywriting" / "SKILL.md").is_file()


def test_render_reports_wing_ids_the_tenant_has_not_enabled(root, tmp_path, capsys):
    onboard.main(["--root", str(root), "--replace", "--enable", "ms-copywriting", "--tenant", "bakery"])
    run(root, "render", "--tenant", "bakery", "--node", "coding", "--runtime", "claude", "--out", str(tmp_path / "out"))
    err = capsys.readouterr().err
    assert "skip xmcp: not enabled for tenant bakery" in err
    assert "node_profile.py enable --tenant bakery --node coding" in err


def test_node_mcps_override_replaces_fill(root, tmp_path):
    out = tmp_path / "out"
    run(root, "render", "--tenant", "bakery", "--node", "coding", "--runtime", "claude", "--out", str(out), "--write")
    text = (out / "project" / ".mcp.json").read_text()
    data = json.loads(text)
    assert data["mcpServers"]["xmcp"] == {"command": "npx", "args": ["-y", "xmcp"], "env": {"X_BEARER": "${X_BEARER}"}}
    assert "FILL" not in text
    # without --node the same card still renders FILL (the card has no mcp block)
    plain = tmp_path / "plain"
    onboard.main(["--root", str(root), "--render-adapter", "claude", "--tenant", "bakery", "--out", str(plain), "--write"])
    assert "FILL:" in (plain / "project" / ".mcp.json").read_text()


def test_rules_block_names_wing_and_links_real_context_only(root, tmp_path):
    out = tmp_path / "out"
    run(root, "render", "--tenant", "bakery", "--node", "coding", "--runtime", "claude", "--out", str(out), "--write")
    rules = (out / "project" / "CLAUDE.md").read_text()
    context = (root / "tenants" / "bakery" / "context").resolve()
    assert "Wing:" in rules and "coding" in rules
    assert "tenant=bakery" in rules
    assert "Brand context" in rules
    assert str(context / "voice.md") in rules and str(context / "offer.md") in rules
    assert str(context / "customer.md") not in rules  # FILL only
    assert "Warm, short." not in rules  # links, never inline
    # without a node, no wing line and no context section
    plain = tmp_path / "plain"
    onboard.main(["--root", str(root), "--render-adapter", "claude", "--tenant", "bakery", "--out", str(plain), "--write"])
    plain_rules = (plain / "project" / "CLAUDE.md").read_text()
    assert "Wing:" not in plain_rules and "Brand context" not in plain_rules and "tenant=" not in plain_rules


def test_enable_is_idempotent(root):
    onboard.main(["--root", str(root), "--replace", "--enable", "fk-payments", "--tenant", "bakery"])
    assert run(root, "enable", "--tenant", "bakery", "--node", "coding") == 0
    first = enabled_ids(root)
    assert first == ["fk-payments", "ms-copywriting", "xmcp"]
    assert run(root, "enable", "--tenant", "bakery", "--node", "coding") == 0
    assert enabled_ids(root) == first


def test_enable_all_tenants_iterates_registry(root, capsys):
    onboard.main(["--root", str(root), "--replace", "--enable", "fk-payments", "--tenant", "bakery"])
    assert run(root, "enable", "--all-tenants", "--node", "coding") == 0
    out = capsys.readouterr()
    assert "bakery" in out.out
    assert "acme" in out.out + out.err  # listed but has no folder: reported, not fatal
    assert enabled_ids(root) == ["fk-payments", "ms-copywriting", "xmcp"]


def test_enable_needs_tenant_or_all(root, capsys):
    assert run(root, "enable", "--node", "coding") == 1
    assert run(root, "enable", "--tenant", "ghost", "--node", "coding") == 1
    assert "no such tenant" in capsys.readouterr().err


def test_onboard_node_flag_directly(root, tmp_path, capsys, monkeypatch):
    out = tmp_path / "out"
    rc = onboard.main(["--root", str(root), "--render-adapter", "claude", "--tenant", "bakery", "--node", "coding", "--out", str(out)])
    assert rc == 0
    assert "coding" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="known: coding"):
        onboard.main(["--root", str(root), "--render-adapter", "claude", "--tenant", "bakery", "--node", "nope"])
    # SNOWGLOVES_NODE is the default
    monkeypatch.setenv("SNOWGLOVES_NODE", "coding")
    with pytest.raises(SystemExit, match="cursor"):
        onboard.main(["--root", str(root), "--render-adapter", "cursor", "--tenant", "bakery", "--out", str(out)])
    # --enable --node merges the wing's modules
    onboard.main(["--root", str(root), "--replace", "--enable", "fk-payments", "--tenant", "bakery"])
    assert onboard.main(["--root", str(root), "--enable", "ms-copywriting", "--tenant", "bakery", "--node", "coding"]) == 0
    assert enabled_ids(root) == ["fk-payments", "ms-copywriting", "xmcp"]


def test_project_precedence_node_over_runtime_yaml(root, tmp_path):
    tdir = root / "tenants" / "bakery"
    rt = yaml.safe_load((tdir / "runtime.yaml").read_text())
    rt["preferences"]["project"] = str(tmp_path / "from-runtime")
    (tdir / "runtime.yaml").write_text(yaml.safe_dump(rt))
    node = onboard.nodes.load_node(root, "coding")
    assert onboard.project_for(tdir, None, node, "bakery") == tmp_path / "from-runtime"
    node["tenants"] = [{"slug": "bakery", "project": str(tmp_path / "from-node")}]
    assert onboard.project_for(tdir, None, node, "bakery") == tmp_path / "from-node"
    assert onboard.project_for(tdir, tmp_path / "given", node, "bakery") == (tmp_path / "given").resolve()

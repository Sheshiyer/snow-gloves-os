import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import onboard  # noqa: E402
from lib import nodes  # noqa: E402

ADAPTERS = ROOT / "adapters"

MODULES = {
    "schema": "snowgloves.modules.v1",
    "version": "0.2.0",
    "agents": [{"slug": "ceo", "role": "Chief Executive Agent"}, {"slug": "interpreter", "role": "Interpreter"}],
    "cards": [
        {"id": "ms-copywriting", "name": "Copywriting", "category": "skills", "kind": "skill", "disposition": "add",
         "repo": "https://github.com/x/y", "source": "1", "risk": "low", "approval": "no",
         "agents": ["interpreter"], "runtimes": ["any"], "summary": "Write page copy."},
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
    "connectors": [{"id": "gmail", "auth": "oauth2",
                    "capabilities": [{"id": "gmail.send_message", "risk": "high", "approval": "yes"}]}],
}

GOOD = {
    "schema": "snowgloves.node.v1",
    "wing": "coding",
    "hostname": "coding-mac",
    "overlay": "coding-mac",
    "location": "paris-office",
    "always_on": True,
    "services": [{"id": "omniroute", "port": 20128}],
    "operator_user": "sg-coding",
    "primary": "claude",
    "runtimes": ["claude", "codex"],
    "modules": ["ms-copywriting", "xmcp", "fk-payments"],
    "mcps": {"xmcp": {"command": "npx", "args": ["-y", "xmcp"], "env": {"X_TOKEN": "${X_TOKEN}"}}},
    "connectors": ["gmail"],
    "tenants": "all",
}


@pytest.fixture
def catalog(tmp_path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "modules.json").write_text(json.dumps(MODULES))
    return onboard.Catalog(tmp_path, ADAPTERS)


def node(**changes):
    data = json.loads(json.dumps(GOOD))
    data.update(changes)
    return data


def test_constants():
    assert nodes.NODE_SCHEMA == "snowgloves.node.v1"
    assert nodes.WINGS == ("marketing", "design", "coding")


def test_valid_node_has_no_problems(catalog):
    assert nodes.validate_node(GOOD, folder="coding", adapters_dir=ADAPTERS, catalog=catalog) == []


def test_schema_and_folder_mismatch_are_reported():
    text = " ".join(nodes.validate_node(node(schema="nope"), folder="design"))
    assert "schema must be snowgloves.node.v1" in text
    assert "does not match folder 'design'" in text
    assert "wing must be one of" in " ".join(nodes.validate_node(node(wing="ops"), folder="ops"))


def test_missing_required_keys_are_listed():
    text = " ".join(nodes.validate_node({"schema": "snowgloves.node.v1"}))
    for key in ("wing", "hostname", "operator_user", "primary", "runtimes", "modules"):
        assert f"missing {key}" in text


def test_hold_and_unknown_ids_are_rejected(catalog):
    problems = nodes.validate_node(node(modules=["ms-copywriting", "openspec", "nope"]), folder="coding", catalog=catalog)
    text = " ".join(problems)
    assert "openspec is on hold" in text and "nope: unknown id" in text
    # connectors go through the same gate
    text = " ".join(nodes.validate_node(node(connectors=["ghost"]), folder="coding", catalog=catalog))
    assert "connectors" in text and "ghost" in text
    # agent ids are not modules
    assert "ceo" in " ".join(nodes.validate_node(node(modules=["ceo"]), folder="coding", catalog=catalog))


def test_runtimes_must_have_adapters_and_contain_primary():
    text = " ".join(nodes.validate_node(node(runtimes=["claude", "vscode"]), folder="coding", adapters_dir=ADAPTERS))
    assert "vscode" in text and "adapter" in text
    text = " ".join(nodes.validate_node(node(primary="cursor"), folder="coding"))
    assert "primary 'cursor' is not in runtimes" in text
    assert "runtimes must not be empty" in " ".join(nodes.validate_node(node(runtimes=[]), folder="coding"))


def test_mcps_need_command_or_url_and_env_var_names():
    text = " ".join(nodes.validate_node(node(mcps={"xmcp": {"args": []}}), folder="coding"))
    assert "mcps.xmcp" in text and "command or url" in text
    text = " ".join(nodes.validate_node(node(mcps={"xmcp": {"command": "npx", "env": {"X_TOKEN": "hunter2"}}}), folder="coding"))
    assert "env.X_TOKEN" in text and "${VAR}" in text
    text = " ".join(nodes.validate_node(node(mcps={"other": {"command": "npx"}}), folder="coding"))
    assert "mcps.other" in text and "not in modules" in text
    assert nodes.validate_node(node(mcps={"xmcp": {"url": "https://mcp.example"}}), folder="coding") == []
    assert "mcps must be a mapping" in " ".join(nodes.validate_node(node(mcps=["xmcp"]), folder="coding"))


def test_tenants_is_all_or_a_list_of_slug_entries():
    assert nodes.validate_node(node(tenants="all"), folder="coding") == []
    assert nodes.validate_node(node(tenants=[{"slug": "acme", "project": "/p"}, {"slug": "bakery"}]), folder="coding") == []
    assert "tenants" in " ".join(nodes.validate_node(node(tenants="some"), folder="coding"))
    assert "slug" in " ".join(nodes.validate_node(node(tenants=[{"name": "acme"}]), folder="coding"))
    assert "Bad Slug" in " ".join(nodes.validate_node(node(tenants=[{"slug": "Bad Slug"}]), folder="coding"))


def test_services_and_flags_have_shapes():
    text = " ".join(nodes.validate_node(node(services=[{"id": "x"}], always_on="yes"), folder="coding"))
    assert "services" in text and "port" in text and "always_on" in text


def test_node_project_and_serves():
    listed = node(tenants=[{"slug": "acme", "project": "~/acme"}, {"slug": "bakery"}, {"slug": "fill", "project": "FILL: later"}])
    assert nodes.node_project(listed, "acme") == Path("~/acme").expanduser()
    assert nodes.node_project(listed, "bakery") is None
    assert nodes.node_project(listed, "fill") is None
    assert nodes.node_project(GOOD, "acme") is None
    assert nodes.node_serves(GOOD, "anyone") is True
    assert nodes.node_serves(listed, "acme") is True and nodes.node_serves(listed, "other") is False


def test_effective_ids_preserves_tenant_order_and_dedupes():
    effective, only_tenant, only_node = nodes.effective_ids(["b", "a", "c", "a"], ["c", "a", "z", "z"])
    assert effective == ["a", "c"]
    assert only_tenant == ["b"]
    assert only_node == ["z"]
    assert nodes.effective_ids([], ["x"]) == ([], [], ["x"])
    assert nodes.allow_ids(GOOD) == ["ms-copywriting", "xmcp", "fk-payments", "gmail"]


def test_list_and_load_nodes(tmp_path):
    assert nodes.list_nodes(tmp_path) == []
    folder = tmp_path / "nodes" / "coding"
    folder.mkdir(parents=True)
    (folder / "node.yaml").write_text(yaml.safe_dump(GOOD, sort_keys=False))
    (tmp_path / "nodes" / "stray").mkdir()
    assert nodes.list_nodes(tmp_path) == ["coding"]
    assert nodes.load_node(tmp_path, "coding")["hostname"] == "coding-mac"
    with pytest.raises(nodes.NodeError, match="known: coding"):
        nodes.load_node(tmp_path, "design")
    (folder / "node.yaml").write_text("- just\n- a list\n")
    with pytest.raises(nodes.NodeError, match="mapping"):
        nodes.load_node(tmp_path, "coding")


def test_real_nodes_validate_against_real_catalog():
    catalog = onboard.Catalog(ROOT, ADAPTERS)
    wings = nodes.list_nodes(ROOT)
    assert set(wings) == set(nodes.WINGS)
    for wing in wings:
        data = nodes.load_node(ROOT, wing)
        assert nodes.validate_node(data, folder=wing, adapters_dir=ADAPTERS, catalog=catalog) == [], wing
        # every mcps entry has a matching catalog card whose own mcp block agrees on the command
        for mid, spec in (data.get("mcps") or {}).items():
            card = catalog.by_id()[mid]
            assert card.get("mcp", {}).get("command") == spec.get("command"), (wing, mid)


def test_all_tenants_skips_fixture_slugs():
    from lib import nodes
    node = {"tenants": "all"}
    assert nodes.node_serves(node, "heyzack")
    assert not nodes.node_serves(node, "_demo")
    explicit = {"tenants": [{"slug": "_demo"}]}
    assert nodes.node_serves(explicit, "_demo")
    assert not nodes.node_serves(explicit, "heyzack")

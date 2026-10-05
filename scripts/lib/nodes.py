"""Machine wings (schema snowgloves.node.v1).

A node is one folder: nodes/<wing>/node.yaml. It says which runtimes a wing
machine runs, which catalog ids that machine may serve, and how its MCP servers
launch. A node never enables anything: a render is the intersection of the
tenant's enabled.yaml and the wing's allow-list, and enabled.yaml stays the one
file skills/connector-gate reads.

    nodes.load_node(root, "coding")                     -> dict
    nodes.validate_node(data, folder="coding", ...)     -> [problems]
    nodes.effective_ids(tenant_ids, nodes.allow_ids(node))
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

NODE_SCHEMA = "snowgloves.node.v1"
WINGS = ("marketing", "design", "coding")
REQUIRED = ("schema", "wing", "hostname", "operator_user", "primary", "runtimes", "modules")
OPTIONAL = ("overlay", "location", "always_on", "services", "mcps", "connectors", "tenants", "gateway", "remote_access")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ENV_REF = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


class NodeError(ValueError):
    pass


# ---------------------------------------------------------------- load


def nodes_dir(root: Path | str) -> Path:
    return Path(root) / "nodes"


def node_path(root: Path | str, wing: str) -> Path:
    return nodes_dir(root) / wing / "node.yaml"


def list_nodes(root: Path | str) -> list[str]:
    base = nodes_dir(root)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "node.yaml").is_file())


def load_node(root: Path | str, wing: str) -> dict:
    """Read nodes/<wing>/node.yaml. Shape checks live in validate_node()."""
    path = node_path(root, wing)
    if not path.is_file():
        known = ", ".join(list_nodes(root)) or "none"
        raise NodeError(f"no node profile for wing {wing!r} ({path} is missing; known: {known})")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise NodeError(f"{path}: not valid YAML ({exc})") from None
    if not isinstance(data, dict):
        raise NodeError(f"{path}: expected a mapping, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------- validate


def mcp_spec_problems(spec) -> list[str]:
    """Shape of one MCP launch spec: command|url, args, env (env values are ${VAR} names only)."""
    if not isinstance(spec, dict):
        return ["launch spec must be a mapping with a command or url"]
    out: list[str] = []
    command, url = spec.get("command"), spec.get("url")
    if not (isinstance(command, str) and command) and not (isinstance(url, str) and url):
        out.append("needs a string command or url")
    if "args" in spec and (not isinstance(spec["args"], list) or not all(isinstance(a, str) for a in spec["args"])):
        out.append("args must be a list of strings")
    env = spec.get("env")
    if env is not None:
        if not isinstance(env, dict):
            out.append("env must be a mapping of VAR -> ${VAR}")
        else:
            for key, value in env.items():
                if not isinstance(value, str) or not ENV_REF.match(value):
                    out.append(f"env.{key} must be a ${{VAR}} reference, never a value")
    return out


def _str_list(value, where: str, problems: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"{where} must be a list of strings")
        return []
    dupes = sorted({v for v in value if value.count(v) > 1})
    if dupes:
        problems.append(f"{where} lists {', '.join(dupes)} more than once")
    return value


def _catalog_problems(catalog, ids: list[str], where: str) -> list[str]:
    """Every id must resolve to an enableable card. Uses onboard.resolve_ids so the refusal text matches."""
    if not ids:
        return []
    import onboard  # lazy: onboard imports this module

    try:
        _cards, agents = onboard.resolve_ids(catalog, ids)
    except SystemExit as exc:
        text = str(exc).replace("cannot enable:", "", 1)
        return [f"{where}: {line.strip()}" for line in text.splitlines() if line.strip()]
    return [f"{where}: {a} is an agent, not a module" for a in agents]


def _tenants_problems(tenants) -> list[str]:
    if tenants is None or tenants == "all":
        return []
    if not isinstance(tenants, list):
        return ["tenants must be `all` or a list of {slug, project?} entries"]
    out: list[str] = []
    for i, entry in enumerate(tenants):
        if isinstance(entry, str):
            slug, project = entry, None
        elif isinstance(entry, dict):
            slug, project = entry.get("slug"), entry.get("project")
        else:
            out.append(f"tenants[{i}] must be a slug or a {{slug, project?}} mapping")
            continue
        if not isinstance(slug, str) or not SLUG.match(slug):
            out.append(f"tenants[{i}].slug must be a lowercase slug, got {slug!r}")
        if project is not None and not isinstance(project, str):
            out.append(f"tenants[{i}].project must be a path string")
    return out


def validate_node(data, folder: str | None = None, adapters_dir: Path | None = None, catalog=None) -> list[str]:
    """Return every problem with a node mapping. Empty list means valid.

    adapters_dir enables the runtimes-have-adapters check; catalog (an
    onboard.Catalog) enables the modules/connectors-are-enableable check.
    """
    if not isinstance(data, dict):
        return ["node must be a mapping"]
    problems: list[str] = []
    for key in REQUIRED:
        if key not in data:
            problems.append(f"missing {key}")
    if data.get("schema") != NODE_SCHEMA:
        problems.append(f"schema must be {NODE_SCHEMA}")
    wing = data.get("wing")
    if "wing" in data and (not isinstance(wing, str) or wing not in WINGS):
        problems.append(f"wing must be one of {WINGS}, got {wing!r}")
    if folder and wing != folder:
        problems.append(f"wing {wing!r} does not match folder {folder!r}")
    for key in ("hostname", "operator_user", "primary", "overlay", "location"):
        if key in data and not isinstance(data[key], str):
            problems.append(f"{key} must be a string")
    if "always_on" in data and not isinstance(data["always_on"], bool):
        problems.append("always_on must be true or false")

    runtimes = _str_list(data.get("runtimes"), "runtimes", problems)
    if "runtimes" in data and isinstance(data["runtimes"], list) and not runtimes:
        problems.append("runtimes must not be empty")
    primary = data.get("primary")
    if runtimes and primary not in runtimes:
        problems.append(f"primary {primary!r} is not in runtimes")
    if adapters_dir is not None and runtimes:
        from lib import adapters as ad

        known = set(ad.list_adapters(Path(adapters_dir)))
        unknown = [r for r in runtimes if r not in known]
        if unknown:
            problems.append(f"runtimes {', '.join(unknown)} have no adapter (known: {', '.join(sorted(known))})")

    services = data.get("services")
    if services is not None:
        if not isinstance(services, list):
            problems.append("services must be a list of {id, port}")
        else:
            for i, svc in enumerate(services):
                if not isinstance(svc, dict) or not isinstance(svc.get("id"), str) or not isinstance(svc.get("port"), int):
                    problems.append(f"services[{i}] must be {{id: <str>, port: <int>}}")

    modules = _str_list(data.get("modules"), "modules", problems)
    connectors = _str_list(data.get("connectors"), "connectors", problems)
    if catalog is not None:
        problems += _catalog_problems(catalog, modules, "modules")
        problems += _catalog_problems(catalog, connectors, "connectors")

    mcps = data.get("mcps")
    if mcps is not None:
        if not isinstance(mcps, dict):
            problems.append("mcps must be a mapping of id -> launch spec")
        else:
            allowed = set(modules) | set(connectors)
            for mid, spec in mcps.items():
                problems += [f"mcps.{mid}: {p}" for p in mcp_spec_problems(spec)]
                if allowed and mid not in allowed:
                    problems.append(f"mcps.{mid}: not in modules (mcps never enables anything; list the id under modules too)")

    problems += _tenants_problems(data.get("tenants", "all"))

    gateway = data.get("gateway")
    if gateway is not None:
        if not isinstance(gateway, dict) or not isinstance(gateway.get("url"), str):
            problems.append("gateway must be a mapping with a string url")
        elif "key_ref" in gateway and not isinstance(gateway["key_ref"], str):
            problems.append("gateway.key_ref must be a reference string (keychain:<item>), never a key")
    remote = data.get("remote_access")
    if remote is not None and not isinstance(remote, dict):
        problems.append("remote_access must be a mapping")
    return problems


# ---------------------------------------------------------------- queries


def tenant_entry(node: dict, slug: str) -> dict | None:
    tenants = node.get("tenants", "all")
    if not isinstance(tenants, list):
        return None
    for entry in tenants:
        if isinstance(entry, str) and entry == slug:
            return {"slug": slug}
        if isinstance(entry, dict) and entry.get("slug") == slug:
            return entry
    return None


def node_serves(node: dict, slug: str) -> bool:
    """`tenants: all` means every registered brand; fixture tenants (slug starting with `_`) are never implied.

    A wing can still name `_demo` explicitly in a tenants list."""
    tenants = node.get("tenants", "all")
    if tenants is None or tenants == "all":
        return not slug.startswith("_")
    return tenant_entry(node, slug) is not None


def node_project(node: dict, slug: str) -> Path | None:
    """The project folder this node pins for a tenant, if the entry names one."""
    entry = tenant_entry(node, slug) or {}
    project = entry.get("project")
    if isinstance(project, str) and project and not project.upper().startswith("FILL"):
        return Path(project).expanduser()
    return None


def allow_ids(node: dict) -> list[str]:
    """Every id the wing may serve: modules first, then connectors, in file order."""
    return list(dict.fromkeys([*(node.get("modules") or []), *(node.get("connectors") or [])]))


def effective_ids(tenant_ids: list[str], node_modules: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Intersect the tenant's enabled ids with the wing's allow-list.

    Returns (effective, only_in_tenant, only_in_node). Tenant order is kept and
    duplicates are dropped; nothing here enables anything.
    """
    allow = set(node_modules)
    seen: set[str] = set()
    effective: list[str] = []
    only_in_tenant: list[str] = []
    for ident in tenant_ids:
        if ident in seen:
            continue
        seen.add(ident)
        (effective if ident in allow else only_in_tenant).append(ident)
    tenant_set = set(tenant_ids)
    only_in_node = list(dict.fromkeys(i for i in node_modules if i not in tenant_set))
    return effective, only_in_tenant, only_in_node

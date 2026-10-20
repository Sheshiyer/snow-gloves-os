"""Bounded, read-only tenant configuration projection; never runtime evidence."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

MAX_BYTES = 262144
MAX_ROWS = 128
CONTROL_ROLES = frozenset({"ceo", "cto", "chief-of-staff", "librarian", "interpreter", "dispatcher", "sentinel"})
SOURCE_TYPES = frozenset({"filesystem", "obsidian", "git", "github", "google-drive", "gdrive", "drive", "notebooklm", "url", "web", "manual", "document", "api", "email", "vault"})
ID_RE = re.compile(r"[a-z0-9_][a-z0-9_.-]{0,63}\Z")
SENSITIVE_RE = re.compile(r"(?i)(?:^|[^a-z0-9])(?:secret|password|passwd|credentials?|token|bearer)(?:$|[^a-z0-9])|api[_. -]?key|(?:^|[^a-z0-9])(?:sk-|ghp_|github_pat_)")


def safe_id(value):
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None and not SENSITIVE_RE.search(value)


def _label(value, fallback):
    # Names come only from public catalog fields. Never project arbitrary tenant text.
    return value if isinstance(value, str) and 0 < len(value) <= 96 and re.fullmatch(r"[A-Za-z0-9 &(),.'+/-]+", value) and not SENSITIVE_RE.search(value) else fallback


def open_nofollow(path: Path) -> int:
    """A read-only descriptor for *path*, opening every component without following links."""
    absolute = Path(path).absolute()
    if ".." in absolute.parts:
        raise OSError("relative component in path")
    handles = [os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)]
    try:
        for part in absolute.parts[1:-1]:
            handles.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=handles[-1]))
        return os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=handles[-1])
    finally:
        for fd in reversed(handles):
            os.close(fd)


def read_raw(path: Path, limit=MAX_BYTES):
    """A regular file's bytes and state ("configured", "missing" or "held"), read without following links."""
    try:
        fd = open_nofollow(path)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "held"
    try:
        import stat
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_size > limit:
            return None, "held"
        raw = os.read(fd, limit + 1)
        return (None, "held") if len(raw) > limit else (raw, "configured")
    except OSError:
        return None, "held"
    finally:
        os.close(fd)


def _read(path: Path, limit=MAX_BYTES):
    """Open every path component without following links, including ancestor dirs."""
    raw, state = read_raw(path, limit)
    if raw is None:
        return None, state
    try:
        value = json.loads(raw, object_pairs_hook=_unique_pairs) if path.suffix == ".json" else strict_yaml(raw)
        return value, "configured"
    except (ValueError, TypeError, UnicodeError, yaml.YAMLError, RecursionError):
        return None, "held"


def strict_yaml(raw):
    """Parse YAML refusing aliases, anchors and duplicate keys, rather than accepting ambiguous config."""
    if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in yaml.scan(raw)):
        raise ValueError("YAML aliases are not accepted")
    return yaml.load(raw, Loader=_UniqueLoader)


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    return _unique_pairs(loader.construct_pairs(node))


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _tenant_file(tenant_dir, name, schema=None):
    value, state = _read(tenant_dir / name)
    if state == "configured" and (not isinstance(value, dict) or value.get("tenant") != tenant_dir.name or (schema and value.get("schema") != schema)):
        return None, "held"
    return value, state


def _rows(value):
    return isinstance(value, list) and len(value) <= MAX_ROWS


def read_catalog(repo_root: Path):
    """The catalog, its cards by id, control roles and its state; every reader shares this contract."""
    catalog, catalog_state = _read(repo_root / "catalog" / "modules.json", 1048576)
    cards, controls = {}, []
    if isinstance(catalog, dict) and catalog.get("schema") == "snowgloves.modules.v1" and isinstance(catalog.get("cards"), list) and len(catalog["cards"]) <= 4096 and _rows(catalog.get("agents")):
        duplicate_ids = set()
        for card in catalog["cards"]:
            if isinstance(card, dict) and safe_id(card.get("id")):
                if card["id"] in cards:
                    duplicate_ids.add(card["id"])
                cards[card["id"]] = card
        for ident in duplicate_ids:
            cards.pop(ident, None)
        for agent in catalog["agents"]:
            if isinstance(agent, dict) and safe_id(agent.get("slug")) and agent["slug"] in CONTROL_ROLES and agent["slug"] not in [a["id"] for a in controls]:
                controls.append({"id": agent["slug"], "name": _label(agent.get("role"), agent["slug"])})
    else:
        catalog_state = "held"
    return catalog, cards, controls, catalog_state


def read_templates(repo_root: Path):
    """Preparation-only business role templates and their state."""
    roles, roles_state = _read(repo_root / "catalog" / "business-roles.json")
    templates = []
    if _rows(roles):
        for role in roles:
            if isinstance(role, dict) and safe_id(role.get("id")) and safe_id(role.get("desk")) and safe_id(role.get("control_owner")) and role["control_owner"] in CONTROL_ROLES and role.get("preparation_only") is True and role["id"] not in [r["id"] for r in templates]:
                templates.append({"id": role["id"], "name": _label(role.get("name"), role["id"]), "desk": role["desk"], "controlOwner": role["control_owner"], "preparationOnly": True})
    else:
        roles_state = "held"
    return templates, roles_state


def card_gate(card, known_roles):
    """A card's closed-enum category, disposition, risk and approval, and whether a tenant may use it."""
    category = card.get("category") if card.get("category") in ("skills", "mcp", "connector", "plugin", "playbook", "mod") else "unknown"
    disposition = card.get("disposition") if card.get("disposition") in ("add", "pointer", "hold", "refuse") else "unknown"
    risk = card.get("risk") if card.get("risk") in ("low", "medium", "high") else "unknown"
    approval = card.get("approval") if card.get("approval") in ("yes", "no") else "unknown"
    permitted = category != "unknown" and disposition in ("add", "pointer") and risk != "unknown" and approval != "unknown" and card.get("enableable") is True and _rows(card.get("agents")) and all(isinstance(a, str) and a in known_roles for a in card["agents"])
    return category, disposition, risk, approval, permitted


def read_manifest(tenant_dir: Path):
    """The tenant's MANIFEST.yaml and its state; a manifest naming another tenant is held."""
    return _tenant_file(tenant_dir, "MANIFEST.yaml")


def read_sources(tenant_dir: Path):
    """The tenant's sources.yaml and its state; a foreign tenant or one malformed row holds it all."""
    data, state = _tenant_file(tenant_dir, "sources.yaml")
    if state != "configured":
        return None, state
    if not _rows(data.get("sources")):
        return None, "held"
    seen = set()
    for source in data["sources"]:
        if not (isinstance(source, dict) and safe_id(source.get("id")) and isinstance(source.get("type"), str)
                and source["type"] in SOURCE_TYPES and ("tenant" not in source or source["tenant"] == tenant_dir.name)
                and ("ingest" not in source or type(source["ingest"]) is bool) and source["id"] not in seen):
            return None, "held"
        seen.add(source["id"])
    return data, "configured"


def read_enablement(tenant_dir: Path):
    """The tenant's enabled.yaml and its state; one unsafe, malformed or duplicate row holds it all."""
    enabled, state = _tenant_file(tenant_dir, "enabled.yaml", "snowgloves.enabled.v1")
    if state != "configured":
        return None, state
    if not _rows(enabled.get("modules")) or not _rows(enabled.get("agents")):
        return None, "held"
    modules = [item.get("id") if isinstance(item, dict) else item for item in enabled["modules"]]
    for idents in (enabled["agents"], modules):
        if not all(safe_id(ident) for ident in idents) or len(set(idents)) != len(idents):
            return None, "held"
    return enabled, "configured"


def capability_map(repo_root: Path, tenant_dir: Path) -> dict:
    """Only IDs, public labels and closed enums leave this source reader."""
    if not safe_id(tenant_dir.name):
        raise ValueError("invalid tenant")
    catalog, cards, controls, catalog_state = read_catalog(repo_root)

    templates, roles_state = read_templates(repo_root)

    enabled, enabled_state = read_enablement(tenant_dir)
    configured, assigned = [], []
    known_roles = {r["id"] for r in controls + templates}
    # Only control agents exist at runtime (manifests under agents/); a preparation-only
    # template listed under agents cannot be assigned, so it is held, not configured.
    control_ids = {r["id"] for r in controls}
    if enabled_state == "configured":
        for ident in enabled["agents"]:
            assigned.append({"id": ident, "status": "configured" if ident in control_ids else "held"})
        for item in enabled["modules"]:
            ident = item.get("id") if isinstance(item, dict) else item
            card = cards.get(ident, {})
            category, disposition, risk, approval, permitted = card_gate(card, known_roles)
            configured.append({"id": ident, "name": _label(card.get("name"), ident), "category": category, "disposition": disposition, "risk": risk, "approval": approval, "gate": ("approval_required" if approval == "yes" or risk == "high" else "catalog_permitted") if permitted else "held", "roles": sorted({a for a in card.get("agents", []) if isinstance(a, str) and a in known_roles}) if _rows(card.get("agents")) else []})

    runtime, runtime_state = _tenant_file(tenant_dir, "runtime.yaml", "snowgloves.runtime.v1")
    runtime_id = None
    if runtime_state == "configured":
        # Runtime IDs must be published adapter IDs; no arbitrary runtime label leaves config.
        adapters = catalog.get("adapters", []) if catalog_state == "configured" else []
        allowed = {a["id"] for a in adapters if isinstance(a, dict) and safe_id(a.get("id"))} if _rows(adapters) else set()
        if safe_id(runtime.get("primary")) and runtime["primary"] in allowed:
            runtime_id = runtime["primary"]
        else:
            runtime_state = "held"

    source_data, sources_state = read_sources(tenant_dir)
    sources = [{"id": source["id"], "type": source["type"], "admitted": source.get("ingest") is True}
               for source in source_data["sources"]] if sources_state == "configured" else []

    return {"tenant": tenant_dir.name, "status": "source_config_only", "connectionAuth": "unverified", "catalogState": catalog_state, "templatesState": roles_state, "enabledState": enabled_state, "runtimeState": runtime_state, "runtime": runtime_id, "sourcesState": sources_state, "configuredModules": configured, "assignedAgents": assigned, "availableControlRoles": controls, "availableBusinessRoles": templates, "registeredSources": sources}

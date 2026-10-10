#!/usr/bin/env python3
"""JSON bridge for the Claude Code mods in mods/ (sg-rail, sg-connector-gate, sg-approvals).

A mod runs inside Claude Code with no YAML parser, no Node APIs, and no imports
from other plugins, so the platform's rules stay here and each mod calls this
CLI through $.process.run. Every command prints one JSON object.

    sg_mods.py snapshot          [--data-root P] [--tenant T] [--cwd C]
    sg_mods.py gate-table        --tenant T [--data-root P] [--ttl-hours H]
    sg_mods.py request-approval  --tenant T --connector C --capability CAP [--tool NAME] [--data-root P]

snapshot and gate-table only read. request-approval queues a pending ticket the
way scope_guard does, and returns an existing pending ticket for the same
connector and capability instead of adding a second one.

Exit codes: 0 ok, 2 bad input (unknown tenant, unmanaged connector).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths  # noqa: E402
from lib import scope_guard  # noqa: E402

SCHEMA_SNAPSHOT = "snowgloves.mods-snapshot.v1"
SCHEMA_GATE = "snowgloves.mods-gate.v1"
SLUG = re.compile(r"^[a-z0-9_][a-z0-9-]*$")
MANAGED_CATEGORIES = ("mcp", "connector")
DEFAULT_OMNIROUTE = "http://127.0.0.1:20128"
DEFAULT_TTL_HOURS = 24.0
MAX_ITEMS = 50
ISC_LINE = re.compile(r"^- \[([ xX])\] ISC-\d+", re.M)


class InputError(ValueError):
    pass


# ---------------------------------------------------------------- reading


def resolve_data_root(flag: str | None) -> tuple[Path, str]:
    """Where tenants live, and which rule picked it: flag, env, or code-fallback."""
    if flag:
        return paths.data_root(flag), "flag"
    if os.environ.get(paths.ENV, "").strip():
        return paths.data_root(), "env"
    return paths.code_root(), "code-fallback"


def _yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def registered_tenants(data_root: Path) -> list[str]:
    raw = _yaml(data_root / "tenants" / "_registry.yaml").get("tenants") or []
    return [str(t) for t in raw if isinstance(t, (str, int))]


def tenant_dirs(data_root: Path) -> list[str]:
    base = data_root / "tenants"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and SLUG.match(p.name))


def check_slug(tenant: str) -> str:
    if not SLUG.match(tenant or ""):
        raise InputError(f"not a tenant slug: {tenant!r}")
    return tenant


def project_of(data_root: Path, tenant: str) -> Path | None:
    prefs = _yaml(data_root / "tenants" / tenant / "runtime.yaml").get("preferences") or {}
    project = str(prefs.get("project") or "")
    if not project or project.upper().startswith("FILL"):
        return None
    return Path(project).expanduser().resolve()


def resolve_tenant(data_root: Path, flag: str | None, cwd: Path) -> tuple[str | None, str, list[str]]:
    """The tenant a session works for: the flag, else a registered tenant whose
    runtime.yaml project holds cwd, else none. Never falls back to _demo."""
    notes: list[str] = []
    if flag:
        check_slug(flag)
        if not (data_root / "tenants" / flag).is_dir():
            notes.append(f"tenant {flag} has no folder under {data_root / 'tenants'}")
        return flag, "flag", notes
    cwd = cwd.resolve()
    hits = []
    for slug in registered_tenants(data_root):
        project = project_of(data_root, slug)
        if project and (cwd == project or project in cwd.parents):
            hits.append(slug)
    if len(hits) > 1:
        notes.append(f"several tenants claim {cwd}: {', '.join(hits)}; using {hits[0]}")
    if hits:
        return hits[0], "project-match", notes
    return None, "none", notes


def approvals_summary(data_root: Path, tenants: list[str]) -> dict:
    """Pending tickets across tenants. Payload values can hold personal data, so only keys leave."""
    items, by_tenant = [], {}
    for slug in tenants:
        rows = [r for r in _jsonl(data_root / "tenants" / slug / "approvals" / "pending.jsonl")
                if r.get("status", "pending") == "pending" and r.get("id")]
        if rows:
            by_tenant[slug] = len(rows)
        for r in rows:
            payload = r.get("payload")
            items.append({
                "tenant": slug,
                "id": str(r["id"]),
                "connector": str(r.get("connector") or ""),
                "capability": str(r.get("capability") or ""),
                "kind": str(r.get("kind") or ""),
                "risk": str(r.get("risk") or ""),
                "created_at": r.get("created_at") if isinstance(r.get("created_at"), (int, float)) else None,
                "payload_keys": sorted(payload) if isinstance(payload, dict) else [],
            })
    items.sort(key=lambda i: (i["created_at"] or 0), reverse=True)
    return {"pending_total": len(items), "by_tenant": by_tenant, "items": items[:MAX_ITEMS]}


def walk_receipt(data_root: Path, tenant: str | None) -> dict | None:
    candidates = []
    if tenant:
        candidates.append(data_root / "tenants" / tenant / "audit" / "graph-walk.json")
    candidates.append(paths.code_root() / "tenants" / "_demo" / "audit" / "graph-walk.json")
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            return {
                "verdict": str(data.get("verdict") or "?"),
                "events": len(data.get("events") or []),
                "loops": len(data.get("loops") or []),
                "path": str(path),
            }
    return None


def isa_progress(code_root: Path) -> dict | None:
    path = code_root / "ISA.md"
    if not path.is_file():
        return None
    marks = ISC_LINE.findall(path.read_text(encoding="utf-8"))
    return {"checked": sum(1 for m in marks if m.lower() == "x"), "total": len(marks)}


def endpoints(code_root: Path, data_root: Path) -> dict:
    hermes = _yaml(code_root / "config" / "snowgloves.yaml").get("hermes") or {}
    host, port = hermes.get("host") or "127.0.0.1", hermes.get("port") or 4100
    gateway = _yaml(data_root / "fleet.yaml").get("gateway") or {}
    omniroute = str(gateway.get("url") or os.environ.get("OMNIROUTE_URL") or DEFAULT_OMNIROUTE)
    return {"hermes": f"http://{host}:{port}", "omniroute": omniroute.rstrip("/")}


def snapshot(data_root_flag: str | None, tenant_flag: str | None, cwd: Path) -> dict:
    code_root = paths.code_root()
    data_root, source = resolve_data_root(data_root_flag)
    tenant, tenant_source, notes = resolve_tenant(data_root, tenant_flag, cwd)
    registered = registered_tenants(data_root)
    present = tenant_dirs(data_root)
    warnings = list(notes)
    if source == "code-fallback":
        warnings.append("SNOWGLOVES_DATA is unset: reading the public fixtures in this checkout")
        stray = [t for t in present if t not in registered]
        if stray:
            warnings.append(
                "tenants/" + ", tenants/".join(stray)
                + " sit in the platform checkout but not in _registry.yaml; instance data belongs in snow-gloves-ops"
            )
    if tenant is None:
        warnings.append("no tenant resolved: set SNOWGLOVES_TENANT or the mod's tenant option")
    return {
        "schema": SCHEMA_SNAPSHOT,
        "generated_at": int(time.time()),
        "code_root": str(code_root),
        "data_root": str(data_root),
        "data_root_source": source,
        "tenant": tenant,
        "tenant_source": tenant_source,
        "tenants": sorted(set(registered) & set(present)) or present,
        "approvals": approvals_summary(data_root, sorted(set(registered) | set(present))),
        "walk": walk_receipt(data_root, tenant),
        "isa": isa_progress(code_root),
        "endpoints": endpoints(code_root, data_root),
        "warnings": warnings,
    }


# ---------------------------------------------------------------- gate


def catalog_cards(code_root: Path) -> list[dict]:
    path = code_root / "catalog" / "modules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [c for c in data.get("cards") or [] if isinstance(c, dict) and c.get("id")]


def enabled_ids(data_root: Path, tenant: str) -> set[str]:
    modules = _yaml(data_root / "tenants" / tenant / "enabled.yaml").get("modules") or []
    return {str(m["id"]) for m in modules if isinstance(m, dict) and m.get("id")}


def needs_approval(card: dict) -> bool:
    return str(card.get("approval")) == "yes" or card.get("risk") == "high"


def gate_table(data_root_flag: str | None, tenant: str, ttl_hours: float, now: float | None = None) -> dict:
    """Everything sg-connector-gate needs to decide an MCP call without another process start."""
    check_slug(tenant)
    data_root, source = resolve_data_root(data_root_flag)
    tdir = data_root / "tenants" / tenant
    if not tdir.is_dir():
        raise InputError(f"unknown tenant {tenant}: no folder at {tdir}")
    now = time.time() if now is None else now
    enabled = enabled_ids(data_root, tenant)
    servers = {}
    for card in catalog_cards(paths.code_root()):
        if card.get("category") not in MANAGED_CATEGORIES:
            continue
        servers[card["id"]] = {
            "category": card["category"],
            "disposition": card.get("disposition"),
            "risk": card.get("risk"),
            "approval": card.get("approval"),
            "enabled": card["id"] in enabled,
            "needs_approval": needs_approval(card),
        }
    cutoff = now - ttl_hours * 3600
    grants = [
        {"connector": r["connector"], "capability": str(r.get("capability") or ""), "id": r.get("id"),
         "decided_at": r["decided_at"]}
        for r in _jsonl(tdir / "approvals" / "history.jsonl")
        if r.get("status") == "approved" and r.get("connector") in servers
        and isinstance(r.get("decided_at"), (int, float)) and r["decided_at"] >= cutoff
    ]
    pending = [
        {"connector": r["connector"], "capability": str(r.get("capability") or ""), "id": r.get("id")}
        for r in _jsonl(tdir / "approvals" / "pending.jsonl")
        if r.get("status", "pending") == "pending" and r.get("connector") in servers
    ]
    return {
        "schema": SCHEMA_GATE,
        "generated_at": int(now),
        "tenant": tenant,
        "data_root": str(data_root),
        "data_root_source": source,
        "ttl_hours": ttl_hours,
        "managed": sorted(servers),
        "servers": servers,
        "grants": grants,
        "pending": pending,
    }


def request_approval(data_root_flag: str | None, tenant: str, connector: str, capability: str,
                     tool: str | None = None) -> dict:
    check_slug(tenant)
    data_root, _ = resolve_data_root(data_root_flag)
    if not (data_root / "tenants" / tenant).is_dir():
        raise InputError(f"unknown tenant {tenant}")
    cards = {c["id"]: c for c in catalog_cards(paths.code_root()) if c.get("category") in MANAGED_CATEGORIES}
    card = cards.get(connector)
    if card is None:
        raise InputError(f"{connector} is not a managed connector in catalog/modules.json")
    for row in _jsonl(data_root / "tenants" / tenant / "approvals" / "pending.jsonl"):
        if (row.get("status", "pending") == "pending" and row.get("connector") == connector
                and str(row.get("capability") or "") == capability):
            return {"ticket": row, "deduped": True}
    payload = {"source": "sg-connector-gate"}
    if tool:
        payload["tool"] = tool
    ticket = scope_guard.queue_ticket(
        tenant, connector, capability, card.get("risk"), payload, root=data_root, kind="mcp-call",
    )
    return {"ticket": ticket, "deduped": False}


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--data-root")
    snap.add_argument("--tenant")
    snap.add_argument("--cwd", default=os.getcwd())
    gate = sub.add_parser("gate-table")
    gate.add_argument("--data-root")
    gate.add_argument("--tenant", required=True)
    gate.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS)
    req = sub.add_parser("request-approval")
    req.add_argument("--data-root")
    req.add_argument("--tenant", required=True)
    req.add_argument("--connector", required=True)
    req.add_argument("--capability", required=True)
    req.add_argument("--tool")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "snapshot":
            out = snapshot(args.data_root, args.tenant, Path(args.cwd))
        elif args.cmd == "gate-table":
            out = gate_table(args.data_root, args.tenant, args.ttl_hours)
        else:
            out = request_approval(args.data_root, args.tenant, args.connector, args.capability, args.tool)
    except InputError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

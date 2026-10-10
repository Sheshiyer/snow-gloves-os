#!/usr/bin/env python3
"""JSON bridge for the Claude Code mods in mods/ (the ten sg-* mods, docs/mods.md).

A mod runs inside Claude Code with no YAML parser, no Node APIs, and no imports
from other plugins, so the platform's rules stay here and each mod calls this
CLI through $.process.run. Every command prints one JSON object.

    sg_mods.py snapshot          [--data-root P] [--tenant T] [--cwd C]
    sg_mods.py gate-table        --tenant T [--data-root P] [--ttl-hours H]
    sg_mods.py request-approval  --tenant T --connector C --capability CAP [--tool NAME] [--data-root P]
    sg_mods.py agents            [--tenant T] [--data-root P]
    sg_mods.py combos            [--db PATH]
    sg_mods.py write-handoff     --cwd DIR [--session ID]            (text on stdin)
    sg_mods.py draft-card        --id ID --source TEXT [--name N] [--cards-dir D]   (validate report on stdin)

snapshot, gate-table, agents and combos only read. request-approval queues a pending ticket the
way scope_guard does, and returns an existing pending ticket for the same
connector and capability instead of adding a second one. write-handoff writes
.project/HANDOFF.md (keeping a backup of the one it replaces) and draft-card writes
a catalog card at disposition hold, which a person reviews; neither installs or enables anything.

Exit codes: 0 ok, 2 bad input (unknown tenant, unmanaged connector).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import paths  # noqa: E402
from lib import scope_guard  # noqa: E402
import check_mod_invariants  # noqa: E402  (its notes() reads a `claude plugin validate --json` report)

SCHEMA_SNAPSHOT = "snowgloves.mods-snapshot.v1"
SCHEMA_GATE = "snowgloves.mods-gate.v1"
SCHEMA_AGENTS = "snowgloves.mods-agents.v1"
SCHEMA_COMBOS = "snowgloves.mods-combos.v1"
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


def add_card_ids(code_root: Path) -> list[str]:
    """Ids of the catalog's mod cards whose disposition is add: the mods sg-guard lets spawn or fetch."""
    return sorted(str(c["id"]) for c in catalog_cards(code_root) if c.get("category") == "mod" and c.get("disposition") == "add")


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


# ---------------------------------------------------------------- agents (sg-org)

# Who answers to whom (AGENTS.md): the Chief of Staff routes, escalates to the CTO, then the CEO.
ESCALATES_TO = {"ceo": None, "cto": "ceo", "chief-of-staff": "cto", "librarian": "chief-of-staff",
                "interpreter": "chief-of-staff", "dispatcher": "chief-of-staff", "sentinel": "chief-of-staff"}
READ_ONLY_AGENTS = {"ceo", "interpreter", "librarian", "sentinel"}  # advisory or auditing: they read, never edit or run
READ_TOOLS = ["Read", "Grep", "Glob"]
WORK_TOOLS = READ_TOOLS + ["Bash"]
MAX_PROMPT = 6000


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def enabled_agents(data_root: Path, tenant: str) -> list[str]:
    raw = _yaml(data_root / "tenants" / tenant / "enabled.yaml").get("agents") or []
    return [str(a) for a in raw if isinstance(a, (str, int))]


def agents_table(data_root_flag: str | None, tenant: str | None) -> dict:
    """The seven agents as Claude subagent specs. A role is offered unless the tenant lists agents and omits it."""
    code_root = paths.code_root()
    data_root, source = resolve_data_root(data_root_flag)
    listed: list[str] = []
    if tenant:
        check_slug(tenant)
        if not (data_root / "tenants" / tenant).is_dir():
            raise InputError(f"unknown tenant {tenant}: no folder under {data_root / 'tenants'}")
        listed = enabled_agents(data_root, tenant)
    restricted = bool(listed)
    registry = _yaml(code_root / "skills" / "registry.yaml").get("agents") or {}
    routing = _yaml(code_root / "workflows" / "skill-hooks.yaml").get("routing") or {}
    warnings: list[str] = []
    out = []
    for adir in sorted((code_root / "agents").iterdir() if (code_root / "agents").is_dir() else []):
        manifest = _yaml(adir / "MANIFEST.yaml")
        slug = str(manifest.get("slug") or adir.name)
        identity = _text(adir / "IDENTITY.md")
        if not identity:
            warnings.append(f"agents/{adir.name} has no IDENTITY.md; skipped")
            continue
        hooks = [{"id": str(h.get("id")), "globs": [str(g) for g in h.get("globs") or []]}
                 for h in ((routing.get(slug) or {}).get("hooks") or []) if isinstance(h, dict)]
        skills = [str(x) for x in registry.get(slug) or []] + [
            str(x) for x in (routing.get(slug) or {}).get("default_skills") or []]
        skills = list(dict.fromkeys(skills))
        readonly = slug in READ_ONLY_AGENTS
        escalates = ESCALATES_TO.get(slug)
        approvals = [str(a) for a in manifest.get("approvals_required") or []]
        lines = [f"You are the {manifest.get('role') or slug} of Snow Gloves OS (agent `{slug}`, layer {manifest.get('layer') or '?'}).",
                 "", identity, "", _text(adir / "SOUL.md"), "", _text(adir / "TOOLS.md"), ""]
        if skills:
            lines.append("Default skills: " + ", ".join(skills))
        if hooks:
            lines.append("Routing hooks: " + "; ".join(f"{h['id']} ({', '.join(h['globs'][:4])})" for h in hooks))
        if approvals:
            lines.append("Needs a person's approval for: " + ", ".join(approvals))
        lines.append("Escalate to " + escalates + " when the task is beyond your role." if escalates else "You are the top of the escalation chain: ask the founder.")
        lines.append("You have read-only tools: report, do not change anything." if readonly else "Run commands only inside the working tree; never write outside it.")
        out.append({
            "slug": slug,
            "role": str(manifest.get("role") or slug),
            "layer": str(manifest.get("layer") or ""),
            "description": identity.split("**Mission:**")[-1].strip().splitlines()[0][:240] if "**Mission:**" in identity
            else f"{manifest.get('role') or slug}: delegate work in this role",
            "prompt": "\n".join(lines)[:MAX_PROMPT],
            "tools": list(READ_TOOLS if readonly else WORK_TOOLS),
            "readonly": readonly,
            "default_skills": skills,
            "hooks": hooks,
            "escalates_to": escalates,
            "enabled": (slug in listed) if restricted else True,
        })
    return {"schema": SCHEMA_AGENTS, "tenant": tenant, "data_root": str(data_root), "data_root_source": source,
            "restricted": restricted, "enabled_agents": listed, "agents": out, "warnings": warnings}


# ---------------------------------------------------------------- combos (sg-omniroute)

DEFAULT_OMNIROUTE_DB = "~/.omniroute/storage.sqlite"


def combos_table(db: str | None) -> dict:
    """OmniRoute combo names and members, read from its own database in read-only mode. No key is read."""
    path = Path(db or os.environ.get("OMNIROUTE_DB") or DEFAULT_OMNIROUTE_DB).expanduser()
    warnings: list[str] = []
    rows: list[dict] = []
    if not path.is_file():
        warnings.append(f"no OmniRoute database at {path}")
    else:
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                for name, raw in con.execute("SELECT name, data FROM combos ORDER BY name"):
                    try:
                        data = json.loads(raw) if isinstance(raw, str) else {}
                    except json.JSONDecodeError:
                        data = {}
                    models = data.get("models") if isinstance(data, dict) else None
                    members = [str(m.get("model") if isinstance(m, dict) else m) for m in models or []]
                    rows.append({"name": str(name), "strategy": str((data or {}).get("strategy") or ""), "members": members})
            finally:
                con.close()
        except sqlite3.Error as exc:
            warnings.append(f"could not read combos: {exc}")
    return {"schema": SCHEMA_COMBOS, "source": str(path), "combos": rows, "warnings": warnings}


# ---------------------------------------------------------------- handoff (sg-handoff)

MAX_HANDOFF = 200_000


def write_handoff(cwd: str, text: str, session: str | None = None) -> dict:
    """Write .project/HANDOFF.md under cwd atomically, keeping a copy of the file it replaces."""
    base = Path(cwd).expanduser()
    if not base.is_dir():
        raise InputError(f"not a directory: {cwd}")
    body = text.strip()
    if not body:
        raise InputError("empty handoff text")
    if len(body) > MAX_HANDOFF:
        raise InputError(f"handoff text over {MAX_HANDOFF} characters")
    folder = base.resolve() / ".project"
    folder.mkdir(exist_ok=True)
    target = folder / "HANDOFF.md"
    backup = None
    if target.is_file():
        backup = folder / f"HANDOFF.md.bak-{int(time.time())}"
        backup.write_bytes(target.read_bytes())
    header = f"<!-- written by sg-handoff {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}" + (f" from session {session}" if session else "") + " -->\n\n"
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".handoff-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(header + body + "\n")
    os.replace(tmp, target)
    return {"path": str(target), "bytes": target.stat().st_size, "backup": str(backup) if backup else None}


# ---------------------------------------------------------------- intake (sg-catalog)

CARD_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
HOLD_FLAGS = [
    ("I1", "hooks tool.check, which can approve a call before the user is asked", lambda hooks, calls, env: "tool.check" in hooks),
    ("I3", "can register a tool, submit a prompt, or act as the user", lambda hooks, calls, env: bool(calls & {"$.tool.register", "$.prompt.submit"})),
    ("I5", "reaches the network with $.http.fetch", lambda hooks, calls, env: "$.http.fetch" in calls),
    ("I6", "writes files or spawns processes itself", lambda hooks, calls, env: bool(calls & {"$.fs.write", "$.process.spawn"})),
]


def draft_card(card_id: str, source: str, report: dict, name: str | None, cards_dir: Path) -> dict:
    """Write a hold card from a `claude plugin validate --json` report. A person reviews it; nothing installs."""
    if not CARD_ID.match(card_id or ""):
        raise InputError(f"not a card id: {card_id!r}")
    if not isinstance(report, dict) or "contents" not in report:
        raise InputError("stdin is not a claude plugin validate --json report")
    hooks = check_mod_invariants.notes(report, "hooks")
    calls = check_mod_invariants.notes(report, "calls")
    env = check_mod_invariants.notes(report, "env reads")
    writes = check_mod_invariants.notes(report, "env writes")
    state = check_mod_invariants.notes(report, "state writes")
    flags = [(rule, why) for rule, why, test in HOLD_FLAGS if test(hooks, calls, env)]
    target = cards_dir / f"{card_id}.md"
    if target.exists():
        raise InputError(f"{target.name} already exists; review it instead of overwriting")
    shown = lambda items: ", ".join(sorted(items)) or "nothing"
    summary = f"Third-party mod from {source}; held for review. {len(flags)} rule flag(s)."
    body = [
        "---", f"id: {card_id}", f'name: "{(name or card_id).replace(chr(34), "")}"', "category: mod", "kind: claude-mod",
        "disposition: hold", 'repo: ""', f'source: "{source.replace(chr(34), "")}"', "risk: high", "approval: yes",
        "agents: []", "hooks: []", "runtimes: [claude]", f'summary: "{summary}"', "---", "",
        f"# {name or card_id}", "",
        "Drafted by `sg_mods.py draft-card` from `claude plugin validate --json`. Mods are not sandboxed, so this card is on `hold`: "
        "it cannot be enabled until the founder reviews it and changes the disposition.", "",
        "## What the validator saw", "", f"- hooks: {shown(hooks)}", f"- calls: {shown(calls)}", f"- env reads: {shown(env)}",
        f"- env writes: {shown(writes)}", f"- state writes: {shown(state)}", "",
        "## Rule flags (docs/mods.md I1 to I6)", "",
    ]
    body += [f"- {rule}: {why}" for rule, why in flags] or ["- none flagged"]
    cards_dir.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(body) + "\n", encoding="utf-8")
    return {"card": str(target), "disposition": "hold", "flags": [r for r, _ in flags], "hooks": sorted(hooks), "calls": sorted(calls)}


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
    ag = sub.add_parser("agents")
    ag.add_argument("--data-root")
    ag.add_argument("--tenant")
    sub.add_parser("cards-add")
    cb = sub.add_parser("combos")
    cb.add_argument("--db")
    ho = sub.add_parser("write-handoff")
    ho.add_argument("--cwd", required=True)
    ho.add_argument("--session")
    dc = sub.add_parser("draft-card")
    dc.add_argument("--id", required=True)
    dc.add_argument("--source", required=True)
    dc.add_argument("--name")
    dc.add_argument("--cards-dir")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "snapshot":
            out = snapshot(args.data_root, args.tenant, Path(args.cwd))
        elif args.cmd == "gate-table":
            out = gate_table(args.data_root, args.tenant, args.ttl_hours)
        elif args.cmd == "agents":
            out = agents_table(args.data_root, args.tenant)
        elif args.cmd == "cards-add":
            out = add_card_ids(paths.code_root())
        elif args.cmd == "combos":
            out = combos_table(args.db)
        elif args.cmd == "write-handoff":
            out = write_handoff(args.cwd, sys.stdin.read(), args.session)
        elif args.cmd == "draft-card":
            try:
                report = json.loads(sys.stdin.read())
            except json.JSONDecodeError:
                raise InputError("stdin is not JSON")
            out = draft_card(args.id, args.source, report, args.name, Path(args.cards_dir) if args.cards_dir else paths.code_root() / "catalog" / "cards")
        else:
            out = request_approval(args.data_root, args.tenant, args.connector, args.capability, args.tool)
    except InputError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

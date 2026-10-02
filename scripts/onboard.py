#!/usr/bin/env python3
"""Snow Gloves onboarding: plan-mode interview, harvest apply, enable, and runtime render.

    python3 scripts/onboard.py --steps
    python3 scripts/onboard.py --prompt cursor
    python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant acme
    python3 scripts/onboard.py --list [--category skills] [--json]
    python3 scripts/onboard.py --enable id,id --tenant acme
    python3 scripts/onboard.py --render-adapter claude --tenant acme [--out DIR] [--write]
    python3 scripts/onboard.py --render-adapter claude --tenant acme --node coding   # wing-scoped render
    python3 scripts/onboard.py --init-tenant          # the interactive sources prompt (make onboard)

Options come from catalog/modules.json (built by scripts/build_catalog.py). Only
`add` and `pointer` items can be enabled; `hold` and `refuse` are refused.

--node <wing> (default $SNOWGLOVES_NODE) reads nodes/<wing>/node.yaml. A render then
emits enabled.yaml[tenant] ∩ the wing's modules plus the wing's MCP launch specs;
--enable also adds the wing's modules. enabled.yaml stays the one authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import adapters as ad  # noqa: E402
from lib import nodes  # noqa: E402

CODE_ROOT = Path(__file__).resolve().parents[1]
ENABLEABLE = ("add", "pointer")
CATEGORIES = ("skills", "mcp", "connector", "plugin", "playbook")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CONTEXT_SECTIONS = ("owner", "company", "customer", "offer", "voice", "proof")
CONTEXT_LINKS = ("voice", "offer", "customer", "company")  # linked from the wing rules block when they hold real text
LIST_SECTIONS = ("agents", "skills", "connectors", "runtimes", "sources")
HARVEST_SECTIONS = ("tenant", *CONTEXT_SECTIONS, "agents", "skills", "connectors", "runtimes", "preferences", "sources", "open questions")
REFUSAL = {
    "hold": "is on hold: it is listed in the catalog but waits on a founder pick and a review before it can be enabled",
    "refuse": "is refused: the catalog reviewed it and decided Snow Gloves will not run it",
}

STEPS = """Snow Gloves onboarding
1. Interview. In the project you have been building, run the prompt for your runtime:
     python3 scripts/onboard.py --prompt <runtime>     (runtimes: {runtimes})
   The agent enters plan mode, asks one decision at a time, and writes snowgloves-harvest.md.
   Missing facts are FILL:, never guesses.
2. Apply. python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant <slug>
   Writes tenants/<slug>/context/, enabled.yaml, and runtime.yaml.
3. Adjust. python3 scripts/onboard.py --list [--category skills]
           python3 scripts/onboard.py --enable id,id --tenant <slug>
4. Render. python3 scripts/onboard.py --render-adapter <runtime> --tenant <slug>          (dry run)
           python3 scripts/onboard.py --render-adapter <runtime> --tenant <slug> --write
"""


# ---------------------------------------------------------------- catalog


def gstack_card(conn: dict) -> dict:
    """A G-Stack connector from modules.json, shaped like a card. The fabric serves it; nothing installs."""
    caps = [c for c in conn.get("capabilities", []) or [] if isinstance(c, dict)]
    risks = [c.get("risk", "low") for c in caps]
    risk = "high" if "high" in risks else "medium" if "medium" in risks else "low"
    ids = ", ".join(c.get("id", "?") for c in caps)
    return {
        "category": "connector",
        "kind": "g-stack",
        "disposition": "add",
        "risk": risk,
        "approval": "yes" if any(str(c.get("approval")).lower() in ("yes", "true") for c in caps) else "no",
        "summary": f"G-Stack connector ({conn.get('auth', 'no auth')}): {ids}" if ids else "G-Stack connector",
        **conn,
    }


def enableable(card: dict) -> bool:
    if card.get("enableable") is False:
        return False
    return card.get("disposition") in ENABLEABLE


class Catalog:
    def __init__(self, root: Path, adapters_dir: Path, modules_path: Path | None = None):
        self.root = root
        self.adapters_dir = adapters_dir
        self.path = modules_path or root / "catalog" / "modules.json"
        self.data: dict | None = None
        if self.path.is_file():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    @property
    def built(self) -> bool:
        return self.data is not None

    def cards(self) -> list[dict]:
        if not self.data:
            return []
        rows = [c for c in self.data.get("cards", []) if isinstance(c, dict) and c.get("id")]
        seen = {c["id"] for c in rows}
        for conn in self.data.get("connectors", []) or []:
            if isinstance(conn, dict) and conn.get("id") and conn["id"] not in seen:
                rows.append(gstack_card(conn))
                seen.add(conn["id"])
        return rows

    def by_id(self) -> dict[str, dict]:
        return {c["id"]: c for c in self.cards()}

    def agents(self) -> list[dict]:
        raw = (self.data or {}).get("agents")
        out: list[dict] = []
        if isinstance(raw, dict):
            raw = [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in raw.items()]
        for entry in raw or []:
            if isinstance(entry, str):
                out.append({"id": entry})
            elif isinstance(entry, dict):
                ident = entry.get("id") or entry.get("slug")
                if ident:
                    out.append({**entry, "id": ident})
        if out:
            return out
        for manifest in sorted((self.root / "agents").glob("*/MANIFEST.yaml")):
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            out.append({"id": data.get("slug", manifest.parent.name), "role": data.get("role", "")})
        return out

    def agent_ids(self) -> set[str]:
        return {a["id"] for a in self.agents()}

    def runtimes(self) -> list[dict]:
        rows = []
        for rid in ad.list_adapters(self.adapters_dir):
            try:
                rows.append(ad.load_adapter(self.adapters_dir, rid))
            except ad.AdapterError as exc:
                print(f"warning: {exc}", file=sys.stderr)
        return rows

    def card_body(self, card_id: str) -> str:
        card = self.by_id().get(card_id) or {}
        if card.get("body"):
            return str(card["body"]).strip()
        path = self.root / "catalog" / "cards" / f"{card_id}.md"
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            text = parts[2] if len(parts) == 3 else ""
        return text.strip()


def resolve_ids(catalog: Catalog, ids: list[str]) -> tuple[list[dict], list[str]]:
    """Split requested ids into enableable cards and agent ids. Anything else stops the run."""
    cards = catalog.by_id()
    agents = catalog.agent_ids()
    chosen: list[dict] = []
    chosen_agents: list[str] = []
    errors: list[str] = []
    for ident in ids:
        if ident in agents and ident not in cards:
            chosen_agents.append(ident)
            continue
        card = cards.get(ident)
        if card is None:
            hint = "" if catalog.built else " (catalog/modules.json is not built; run scripts/build_catalog.py)"
            errors.append(f"{ident}: unknown id{hint}")
            continue
        disposition = card.get("disposition", "")
        if not enableable(card):
            errors.append(f"{ident} {REFUSAL.get(disposition, f'has disposition {disposition!r} and cannot be enabled')}")
            continue
        chosen.append(card)
    if errors:
        raise SystemExit("cannot enable:\n  " + "\n  ".join(errors))
    return chosen, chosen_agents


# ---------------------------------------------------------------- prompt


def option_lines(catalog: Catalog) -> str:
    out: list[str] = ["### Agents (rooms)", ""]
    for a in catalog.agents():
        role = a.get("role") or a.get("name") or ""
        out.append(f"- `{a['id']}`" + (f" — {role}" if role else ""))
    cards = catalog.cards()
    offered = [c for c in cards if enableable(c)]
    groups = (
        ("Skills", ("skills", "playbook")),
        ("Connectors", ("mcp", "connector")),
        ("Plugins", ("plugin",)),
    )
    for title, cats in groups:
        rows = [c for c in offered if c.get("category") in cats]
        out += ["", f"### {title}", ""]
        if not rows:
            out.append("- none offered yet")
            continue
        for c in sorted(rows, key=lambda c: (c.get("disposition") != "add", c["id"])):
            bits = [c.get("disposition", "")]
            if c.get("agents"):
                bits.append("agents " + ",".join(c["agents"]))
            if cats[0] != "skills":
                bits.append(f"risk {c.get('risk', '?')}, approval {c.get('approval', '?')}")
            if c.get("runtimes"):
                bits.append("runtimes " + ",".join(c["runtimes"]))
            out.append(f"- `{c['id']}` — {c.get('summary') or c.get('name', '')} ({'; '.join(bits)})")
    out += ["", "### Runtimes", ""]
    for rt in catalog.runtimes():
        out.append(f"- `{rt['id']}` — {rt['name']} (asks with {rt['question_tool']})")
    blocked = [c for c in cards if not enableable(c)]
    if blocked:
        out += ["", "### Not offered (explain, never enable)", ""]
        out += [f"- `{c['id']}` — {c.get('disposition')}" for c in sorted(blocked, key=lambda c: c["id"])]
    return "\n".join(out)


def render_prompt(catalog: Catalog, runtime: str) -> str:
    adapter = ad.load_adapter(catalog.adapters_dir, runtime)
    template = (CODE_ROOT / "prompts" / "onboard-interview.md").read_text(encoding="utf-8")
    tool = adapter["question_tool"] or ad.FALLBACK_QUESTION_TOOL
    if tool == ad.FALLBACK_QUESTION_TOOL:
        hint = "This runtime has no structured question tool, so use the numbered list described below."
    else:
        hint = "Pass the options as the tool's choices, and allow multi-select where the step says so."
    plan = adapter.get("plan_mode") or (
        "This runtime has no plan mode. Behave as if it were on: read and ask, write nothing until the end."
    )
    if catalog.built:
        status = f"Built catalog: `{catalog.path.relative_to(catalog.root) if catalog.path.is_relative_to(catalog.root) else catalog.path}`, version {catalog.data.get('version', '?')}, {len(catalog.cards())} cards."
    else:
        status = (
            "`catalog/modules.json` is not built yet, so only agents and runtimes are listed. "
            "Write `- FILL: catalog not built` under Skills and Connectors and tell the founder to run "
            "`python3 scripts/build_catalog.py`."
        )
    fields = ad.verify_fields(adapter)
    if fields:
        status += f" The {runtime} adapter has unconfirmed fields ({', '.join(fields)}); if the question tool or plan mode does not exist here, fall back to a numbered list and plain turns."
    values = {
        "runtime": runtime,
        "runtime_name": adapter["name"],
        "question_tool": tool,
        "question_hint": hint,
        "plan_mode": plan,
        "catalog_status": status,
        "options": option_lines(catalog),
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


# ---------------------------------------------------------------- harvest


def harvest_sections(text: str) -> dict[str, str]:
    current: str | None = None
    buckets: dict[str, list[str]] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            buckets.setdefault(current, [])
            continue
        if current:
            buckets[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in buckets.items()}


def list_items(body: str) -> list[tuple[str, str]]:
    """`- id` or `- id: note` lines. `none` and FILL lines are skipped."""
    rows = []
    for line in body.splitlines():
        text = line.strip()
        if not text.startswith(("- ", "* ")):
            continue
        text = text[2:].strip().strip("`")
        if not text or text.lower() == "none" or text.upper().startswith("FILL"):
            continue
        ident, _, note = text.partition(":")
        rows.append((ident.strip().strip("`"), note.strip()))
    return rows


def key_values(body: str) -> dict[str, str]:
    out = {}
    for line in body.splitlines():
        text = line.strip().lstrip("-* ").strip()
        if ":" in text:
            key, _, value = text.partition(":")
            key = key.strip().strip("`")
            if key:
                out[key] = value.strip().strip("`")
    return out


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_tenant(root: Path, slug: str, name: str) -> tuple[Path, list[str]]:
    """Create the tenant the way tenant_new.sh does, without touching an existing one."""
    tdir = root / "tenants" / slug
    notes = []
    if not tdir.is_dir():
        for sub in ("sources", "connectors", "approvals", "audit", "agents", "wiki", "docs"):
            (tdir / sub).mkdir(parents=True, exist_ok=True)
        notes.append(f"created tenant {tdir}")
    manifest = tdir / "MANIFEST.yaml"
    if not manifest.exists():
        manifest.write_text(
            f"tenant: {slug}\n"
            f"business_name: {json.dumps(name)}\n"
            f"created_at: {now()}\n"
            "paperclip:\n"
            '  company_id: ""    # fill in after paperclip company exists\n'
            '  lane_prefix: ""\n'
            "isolation: strict\n"
            "status: active\n",
            encoding="utf-8",
        )
    registry = root / "tenants" / "_registry.yaml"
    text = registry.read_text(encoding="utf-8") if registry.exists() else "tenants:\n"
    if not re.search(rf"^\s*-\s*{re.escape(slug)}(\s|#|$)", text, re.M):
        registry.write_text(text.rstrip("\n") + f"\n  - {slug}  # {name}\n", encoding="utf-8")
        notes.append(f"registered {slug} in tenants/_registry.yaml")
    return tdir, notes


def write_enabled(tdir: Path, slug: str, cards: list[dict], agents: list[str]) -> Path:
    fields = ("id", "category", "kind", "disposition", "risk", "approval")
    data = {
        "schema": "snowgloves.enabled.v1",
        "tenant": slug,
        "updated_at": now(),
        "agents": agents,
        "modules": [{k: c.get(k, "") for k in fields} for c in cards],
    }
    path = tdir / "enabled.yaml"
    path.write_text(
        "# Written by scripts/onboard.py. Credentials do not go in this file.\n"
        "# Only add/pointer ids appear here; hold and refused ids are never enabled.\n"
        + yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return path


def read_enabled(tdir: Path) -> tuple[list[str], list[str]]:
    path = tdir / "enabled.yaml"
    if not path.is_file():
        return [], []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ids = [m["id"] for m in data.get("modules", []) or [] if isinstance(m, dict) and m.get("id")]
    return ids, list(data.get("agents", []) or [])


def apply_harvest(catalog: Catalog, harvest: Path, slug: str) -> list[str]:
    if not harvest.is_file():
        raise SystemExit(f"harvest file not found: {harvest}")
    text = harvest.read_text(encoding="utf-8")
    sections = harvest_sections(text)
    missing = [name for name in HARVEST_SECTIONS if name not in sections]
    if missing:
        raise SystemExit("harvest is missing headings: " + ", ".join(missing))
    head = key_values(sections["tenant"])
    named = head.get("slug", "")
    if named and not named.upper().startswith("FILL") and named != slug:
        raise SystemExit(f"harvest names tenant {named!r} but --tenant is {slug!r}")
    name = head.get("name", "") or slug
    if name.upper().startswith("FILL"):
        name = slug

    # validate every choice before writing anything
    ids = [i for sec in ("agents", "skills", "connectors") for i, _ in list_items(sections[sec])]
    cards, agents = resolve_ids(catalog, ids)
    runtimes = list_items(sections["runtimes"])
    known = set(ad.list_adapters(catalog.adapters_dir))
    bad = [r for r, _ in runtimes if r not in known]
    if bad:
        raise SystemExit(f"unknown runtime(s): {', '.join(bad)} (known: {', '.join(sorted(known))})")

    tdir, notes = ensure_tenant(catalog.root, slug, name)
    context = tdir / "context"
    context.mkdir(exist_ok=True)
    for key in CONTEXT_SECTIONS:
        body = sections[key] or f"FILL: the harvest left {key} blank."
        (context / f"{key}.md").write_text(f"# {key.title()}\n\nSource: `raw/harvest.md`.\n\n{body}\n", encoding="utf-8")
    fills = [line.strip() for line in text.splitlines() if "FILL:" in line]
    open_q = sections["open questions"] or "\n".join(fills) or "None."
    (context / "open-questions.md").write_text(f"# Open questions\n\n{open_q}\n", encoding="utf-8")
    raw = tdir / "raw"
    raw.mkdir(exist_ok=True)
    (raw / "harvest.md").write_text(text, encoding="utf-8")

    write_enabled(tdir, slug, cards, agents)
    primary = next((r for r, note in runtimes if "primary" in note.lower()), runtimes[0][0] if runtimes else None)
    runtime = {
        "schema": "snowgloves.runtime.v1",
        "tenant": slug,
        "updated_at": now(),
        "primary": primary,
        "runtimes": [{"id": r, "primary": r == primary} for r, _ in runtimes],
        "preferences": key_values(sections["preferences"]),
    }
    (tdir / "runtime.yaml").write_text(
        "# Written by scripts/onboard.py from the interview. Edit freely.\n" + yaml.safe_dump(runtime, sort_keys=False),
        encoding="utf-8",
    )

    sources = [s for s, _ in list_items(sections["sources"])]
    src_file = tdir / "sources.yaml"
    if not src_file.exists():
        src_file.write_text(
            yaml.safe_dump(
                {"tenant": slug, "sources": [{"path": s, "kind": "auto", "ingest": True} for s in sources]},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    elif sources:
        listed = src_file.read_text(encoding="utf-8")
        new = [s for s in sources if s not in listed]
        if new:
            notes.append(f"sources.yaml already exists and was not changed; add by hand: {', '.join(new)}")
    notes.append(f"wrote {context}/, enabled.yaml ({len(cards)} modules, {len(agents)} agents), runtime.yaml")
    if fills:
        notes.append(f"{len(fills)} FILL: line(s) remain; see context/open-questions.md")
    return notes


# ---------------------------------------------------------------- enable / list / render


def enable(catalog: Catalog, slug: str, raw: str, replace: bool) -> Path:
    tdir = catalog.root / "tenants" / slug
    if not tdir.is_dir():
        raise SystemExit(f"no such tenant: {slug} (run --apply-harvest or scripts/tenant_new.sh first)")
    wanted = [p.strip() for p in raw.split(",") if p.strip()]
    prior_ids, prior_agents = ([], []) if replace else read_enabled(tdir)
    # prior ids are re-checked so a card that moved to hold since last time drops out loudly
    cards, agents = resolve_ids(catalog, list(dict.fromkeys(prior_ids + wanted)))
    agents = list(dict.fromkeys(prior_agents + agents))
    return write_enabled(tdir, slug, cards, agents)


def list_text(catalog: Catalog, category: str | None) -> str:
    if not catalog.built:
        return f"catalog/modules.json not found at {catalog.path}. Run: python3 scripts/build_catalog.py\n"
    rows = [c for c in catalog.cards() if category is None or c.get("category") == category]
    out: list[str] = []
    for disposition, title in (("add", "offered"), ("pointer", "pointer (reference only)"), ("hold", "on hold (not enableable)"), ("refuse", "refused (not enableable)")):
        block = sorted((c for c in rows if c.get("disposition") == disposition), key=lambda c: c["id"])
        if not block:
            continue
        out.append(title.upper())
        for c in block:
            out.append(f"  - {c['id']} | {c.get('category', '?')} | {c.get('kind', '?')} | risk {c.get('risk', '?')} | {c.get('repo') or 'no repo'}")
            if c.get("summary"):
                out.append(f"    {c['summary']}")
    return "\n".join(out) + "\n" if out else "no cards match\n"


def has_real_text(text: str) -> bool:
    """True when a context file says something beyond its heading, Source line, and FILL: markers."""
    for line in text.splitlines():
        body = line.strip().lstrip("-*").strip()
        if not body or body.startswith("#") or body.startswith("Source:") or body.upper().startswith("FILL"):
            continue
        return True
    return False


def context_links_for(tdir: Path) -> list[Path]:
    """Absolute paths of the tenant context files worth linking (never inlined)."""
    out: list[Path] = []
    for key in CONTEXT_LINKS:
        path = tdir / "context" / f"{key}.md"
        if path.is_file() and has_real_text(path.read_text(encoding="utf-8")):
            out.append(path.resolve())
    return out


def project_for(tdir: Path, given: Path | None, node: dict | None = None, slug: str | None = None) -> Path:
    """{project} is the founder's project, never the Snow Gloves checkout by accident.

    Precedence: --project > node.tenants[slug].project > runtime.yaml preferences.project > the tenant folder.
    """
    if given:
        return given.expanduser().resolve()
    if node is not None and slug:
        pinned = nodes.node_project(node, slug)
        if pinned is not None:
            return pinned
    runtime = tdir / "runtime.yaml"
    if runtime.is_file():
        prefs = (yaml.safe_load(runtime.read_text(encoding="utf-8")) or {}).get("preferences") or {}
        if prefs.get("project") and not str(prefs["project"]).upper().startswith("FILL"):
            return Path(str(prefs["project"])).expanduser()
    return tdir


def render(
    catalog: Catalog,
    runtime: str,
    slug: str,
    out: Path | None,
    project: Path | None,
    write: bool,
    node: dict | None = None,
) -> int:
    adapter = ad.load_adapter(catalog.adapters_dir, runtime)
    tdir = catalog.root / "tenants" / slug
    if not tdir.is_dir():
        raise SystemExit(f"no such tenant: {slug}")
    ids, agents = read_enabled(tdir)
    wing = None
    context_links: list[Path] | None = None
    if node is not None:
        wing = node.get("wing") or "unknown"
        allowed_runtimes = node.get("runtimes") or []
        if runtime not in allowed_runtimes:
            raise SystemExit(
                f"runtime {runtime!r} is not in the {wing} wing profile (runtimes: {', '.join(allowed_runtimes) or 'none'}); "
                f"pick one of those or edit nodes/{wing}/node.yaml"
            )
        if not nodes.node_serves(node, slug):
            raise SystemExit(f"tenant {slug!r} is not served by the {wing} wing (see tenants: in nodes/{wing}/node.yaml)")
        ids, only_tenant, only_node = nodes.effective_ids(ids, nodes.allow_ids(node))
        for ident in only_tenant:
            print(f"skip {ident}: not in wing profile {wing}", file=sys.stderr)
        for ident in only_node:
            print(
                f"skip {ident}: not enabled for tenant {slug} "
                f"(run scripts/fleet/node_profile.py enable --tenant {slug} --node {wing})",
                file=sys.stderr,
            )
        context_links = context_links_for(tdir)
    cards_by_id = catalog.by_id()
    items = []
    for ident in ids:
        card = cards_by_id.get(ident)
        if card is None:
            print(f"skip {ident}: no longer in the catalog", file=sys.stderr)
        elif not enableable(card):
            print(f"skip {ident} {REFUSAL.get(card.get('disposition'), 'is not enableable')}", file=sys.stderr)
        else:
            items.append(card)
    if out:
        roots = {"home": out / "home", "project": out / "project", "tenant": out / "tenant"}
    else:
        roots = {"home": Path.home(), "project": project_for(tdir, project, node, slug), "tenant": tdir}
    plan = ad.render_plan(
        adapter, items, agents, slug, roots,
        card_bodies={c["id"]: catalog.card_body(c["id"]) for c in items},
        in_sandbox=out is not None,
        node=node,
        context_links=context_links,
    )
    mode = "write" if write else "dry run"
    scope = f"; wing {wing}" if wing else ""
    print(f"render {runtime} for {slug} ({mode}; {len(items)} modules, {len(agents)} agents{scope})")
    for path, content in plan.files.items():
        print(f"  {'wrote' if write else 'would write'} {path} ({len(content.encode())} bytes)")
    for line in plan.skipped:
        print(f"  skip {line}")
    for note in plan.notes:
        print(f"  note {note}")
    if write:
        ad.write_plan(plan)
    else:
        print("nothing written; add --write to apply")
    return 0


# ---------------------------------------------------------------- legacy interactive


def init_tenant(root: Path) -> int:
    """The original onboarding.sh prompt: business name, slug, source paths -> sources.yaml."""
    print("==> Snow Gloves Onboarding")
    name = input("Business name: ").strip()
    slug = input("Tenant slug (lowercase, no spaces): ").strip()
    if not SLUG.match(slug):
        raise SystemExit(f"bad slug: {slug!r}")
    tdir = root / "tenants" / slug
    for sub in ("sources", "wiki", "docs", "audit"):
        (tdir / sub).mkdir(parents=True, exist_ok=True)
    print("Where do your source files live? (one path per line, blank to finish)")
    sources = []
    while True:
        path = input("  path: ").strip()
        if not path:
            break
        sources.append(path)
    lines = [
        f"tenant: {slug}",
        f"business_name: {json.dumps(name)}",
        f"created_at: {now()}",
        "paperclip:",
        f"  port: {os.environ.get('PAPERCLIP_PORT', '3100')}",
        f"  instance: {os.environ.get('PAPERCLIP_INSTANCE', 'default')}",
        "hermes:",
        f"  port: {os.environ.get('HERMES_PORT', '4100')}",
        "sources:" + ("" if sources else " []"),
    ]
    for s in sources:
        lines += [f"  - path: {json.dumps(s)}", "    kind: auto", "    ingest: true"]
    (tdir / "sources.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"==> Wrote {tdir / 'sources.yaml'}")
    print(f"==> Next: run 'python3 scripts/ingest.py {slug}' to start ingestion.")
    print(f"==> Then:  python3 scripts/onboard.py --prompt <runtime>   (plan-mode interview)")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Snow Gloves onboarding", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--steps", action="store_true", help="print the onboarding steps")
    p.add_argument("--prompt", metavar="RUNTIME", help="print the plan-mode interview prompt for a runtime")
    p.add_argument("--apply-harvest", type=Path, metavar="FILE", help="apply snowgloves-harvest.md to --tenant")
    p.add_argument("--enable", metavar="IDS", help="comma-separated card or agent ids to enable for --tenant")
    p.add_argument("--replace", action="store_true", help="with --enable: replace the list instead of adding")
    p.add_argument("--render-adapter", metavar="RUNTIME", help="emit runtime files for --tenant's enabled items")
    p.add_argument("--write", action="store_true", help="with --render-adapter: write files (default is a dry run)")
    p.add_argument("--out", type=Path, help="with --render-adapter: render under this folder instead of real paths")
    p.add_argument("--project", type=Path, help="project folder for {project} paths (default: runtime.yaml preferences.project, else the tenant folder)")
    p.add_argument("--list", action="store_true", help="print the catalog")
    p.add_argument("--category", choices=CATEGORIES)
    p.add_argument("--json", action="store_true", help="with --list: print JSON")
    p.add_argument("--tenant", metavar="SLUG")
    p.add_argument(
        "--node", metavar="WING", default=os.environ.get("SNOWGLOVES_NODE"),
        help="machine wing (nodes/<wing>/node.yaml). With --render-adapter: render only ids enabled for the tenant "
             "AND listed by the wing, using the wing's MCP launch specs. With --enable: also enable the wing's modules. "
             "Default: $SNOWGLOVES_NODE",
    )
    p.add_argument("--init-tenant", action="store_true", help="interactive tenant + sources prompt")
    p.add_argument("--root", type=Path, default=Path(os.environ.get("SNOWGLOVES_ROOT", CODE_ROOT)), help=argparse.SUPPRESS)
    p.add_argument("--adapters-dir", type=Path, default=CODE_ROOT / "adapters", help=argparse.SUPPRESS)
    p.add_argument("--catalog", type=Path, help="path to modules.json (default: <root>/catalog/modules.json)")
    args = p.parse_args(argv)

    catalog = Catalog(args.root, args.adapters_dir, args.catalog)
    if args.tenant and not SLUG.match(args.tenant):
        raise SystemExit(f"bad tenant slug: {args.tenant!r} (lowercase letters, digits, dashes)")
    needs_tenant = args.apply_harvest or args.enable or args.render_adapter
    if needs_tenant and not args.tenant:
        raise SystemExit("--apply-harvest, --enable, and --render-adapter need --tenant <slug>")

    node: dict | None = None
    if args.node:
        try:
            node = nodes.load_node(args.root, args.node)
        except nodes.NodeError as exc:
            raise SystemExit(str(exc)) from None
        problems = nodes.validate_node(
            node, folder=args.node, adapters_dir=args.adapters_dir, catalog=catalog if catalog.built else None
        )
        if problems:
            print(f"nodes/{args.node}/node.yaml is not valid:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 2

    try:
        if args.steps:
            print(STEPS.format(runtimes=", ".join(ad.list_adapters(catalog.adapters_dir))), end="")
            return 0
        if args.prompt:
            print(render_prompt(catalog, args.prompt), end="")
            return 0
        if args.init_tenant:
            return init_tenant(args.root)
        did = False
        if args.apply_harvest:
            for note in apply_harvest(catalog, args.apply_harvest, args.tenant):
                print(note)
            did = True
        if args.enable:
            raw = args.enable
            if node is not None:
                wanted = [s.strip() for s in raw.split(",") if s.strip()]
                raw = ",".join([*wanted, *(node.get("modules") or [])])
            path = enable(catalog, args.tenant, raw, args.replace)
            print(f"wrote {path}")
            did = True
        if args.render_adapter:
            render(catalog, args.render_adapter, args.tenant, args.out, args.project, args.write, node=node)
            did = True
        if args.list:
            if args.json:
                rows = [c for c in catalog.cards() if args.category is None or c.get("category") == args.category]
                print(json.dumps(rows, indent=2))
            else:
                print(list_text(catalog, args.category), end="")
            did = True
        if not did:
            print(STEPS.format(runtimes=", ".join(ad.list_adapters(catalog.adapters_dir))), end="")
        return 0
    except ad.AdapterError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    raise SystemExit(main())

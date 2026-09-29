#!/usr/bin/env python3
"""Learning edge: propose constraints (+ optional hook diffs) from walk/Sentinel/enabled.

Dry-run is the default. --write applies workflows/constraints.yaml.
skill-hooks.yaml is wide blast radius: never apply unless the tenant
approval_mode is allow-graph-write; otherwise write an approvals ticket.

  python3 scripts/graph_upgrade.py
  python3 scripts/graph_upgrade.py --tenant acme --write

make upgrade remains platform VERSION migrations (scripts/upgrade.py).
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ENABLEABLE = {"add", "pointer"}
BLOCKED = {"hold", "refuse"}
ALLOW_HOOK_WRITE = {"allow-graph-write"}
FALLBACK_RE = re.compile(r"fallback_count:\s*(\d+)")


def load_yaml(path: Path):
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def parse_evolution_drift(agents_dir: Path) -> list[dict]:
    """Latest sentinel fallback_count per agent. A count that does not change routing is a report."""
    reports = []
    if not agents_dir.is_dir():
        return reports
    for ev in sorted(agents_dir.glob("*/EVOLUTION.md")):
        text = ev.read_text()
        counts = [int(m.group(1)) for m in FALLBACK_RE.finditer(text)]
        latest = counts[0] if counts else 0  # first hit is the newest (appended after heading)
        reports.append({
            "agent": ev.parent.name,
            "fallback_count": latest,
            "kind": "report" if latest else "ok",
            "path": str(ev),
        })
    return reports


def load_walk_reds(receipt_path: Path) -> list[dict]:
    if not receipt_path.is_file():
        return []
    data = json.loads(receipt_path.read_text())
    reds = []
    for ev in data.get("events") or []:
        if ev.get("verdict") == "RED":
            reds.append(ev)
    for loop in data.get("loops") or []:
        if loop.get("verdict") == "RED" or loop.get("VERDICT") == "RED":
            reds.append(loop)
    return reds


def catalog_by_id(modules_path: Path) -> dict:
    data = load_yaml(modules_path) if modules_path.suffix in {".yaml", ".yml"} else {}
    if modules_path.suffix == ".json" and modules_path.is_file():
        data = json.loads(modules_path.read_text())
    cards = data.get("cards") or data.get("modules") or []
    return {c["id"]: c for c in cards if isinstance(c, dict) and c.get("id")}


def enabled_modules(tenant_dir: Path) -> list[dict]:
    data = load_yaml(tenant_dir / "enabled.yaml")
    return [m for m in (data.get("modules") or []) if isinstance(m, dict) and m.get("id")]


def approval_mode(tenant_dir: Path) -> str:
    rt = load_yaml(tenant_dir / "runtime.yaml")
    prefs = rt.get("preferences") or {}
    return str(prefs.get("approval_mode") or "always-ask")


def hook_skills(hooks: dict, agent: str, hook_id: str) -> list:
    cfg = (hooks.get("routing") or {}).get(agent) or {}
    for h in cfg.get("hooks") or []:
        if h.get("id") == hook_id:
            return list(h.get("skills") or [])
    return []


def propose_constraints(walk_reds: list[dict], hooks: dict) -> list[dict]:
    out = []
    for ev in walk_reds:
        if not isinstance(ev, dict) or "expected" not in ev:
            continue
        if not ev.get("silent_fallback") and ev.get("hook") == "default-fallback":
            continue
        expect = ev.get("expected") or {}
        agent, hook = expect.get("agent"), expect.get("hook")
        if not agent or not hook or hook == "default-fallback":
            continue
        title = ((ev.get("task") or {}).get("title") if isinstance(ev.get("task"), dict) else None)
        if not title:
            # Reconstruct a glob from the fixture id / family so the splitter can attach Y.
            family = ev.get("family") or ev.get("id") or "recover"
            title = str(family)
        glob = f"*{title.lower().strip()}*"
        skills = hook_skills(hooks, agent, hook)
        out.append({
            "id": f"walk-{ev.get('id') or family}",
            "source": "graph-walk",
            "when": {"globs": [glob]},
            "then": {"agent": agent, "hook": hook, "skills": skills},
        })
    return out


def propose_hook_diffs(
    enabled: list[dict],
    catalog: dict,
    hooks: dict,
) -> list[dict]:
    diffs = []
    for mod in enabled:
        cid = mod["id"]
        card = catalog.get(cid) or {}
        disp = card.get("disposition") or mod.get("disposition")
        if disp in BLOCKED or disp not in ENABLEABLE:
            continue
        if card.get("enableable") is False:
            continue
        mapped = card.get("hooks") or []
        if not mapped:
            continue
        for ref in mapped:
            if not isinstance(ref, str) or "." not in ref:
                continue
            agent, hook_id = ref.split(".", 1)
            current = hook_skills(hooks, agent, hook_id)
            if not current and agent not in (hooks.get("routing") or {}):
                continue
            if cid in current:
                continue
            diffs.append({
                "card": cid,
                "disposition": disp,
                "agent": agent,
                "hook": hook_id,
                "add_skill": cid,
                "blast_radius": "wide",
            })
    return diffs


def merge_constraints(existing: list, proposed: list) -> list:
    by_id = {c.get("id"): c for c in existing if isinstance(c, dict) and c.get("id")}
    for c in proposed:
        by_id[c["id"]] = c
    return list(by_id.values())


def queue_hook_ticket(tenant_dir: Path, tenant: str, diffs: list[dict]) -> dict:
    qdir = tenant_dir / "approvals"
    qdir.mkdir(parents=True, exist_ok=True)
    ticket = {
        "id": f"APR-{int(time.time())}-{secrets.token_hex(3)}",
        "tenant": tenant,
        "kind": "graph-hook-diff",
        "blast_radius": "wide",
        "status": "pending",
        "created_at": int(time.time()),
        "payload": {"hook_diffs": diffs},
    }
    (qdir / "pending.jsonl").open("a").write(json.dumps(ticket) + "\n")
    return ticket


def apply_hook_diffs(hooks_path: Path, hooks: dict, diffs: list[dict]) -> None:
    routing = hooks.setdefault("routing", {})
    for d in diffs:
        agent = routing.setdefault(d["agent"], {})
        found = False
        for h in agent.get("hooks") or []:
            if h.get("id") == d["hook"]:
                skills = list(h.get("skills") or [])
                if d["add_skill"] not in skills:
                    skills.append(d["add_skill"])
                    h["skills"] = skills
                found = True
                break
        if not found:
            continue
    hooks_path.write_text(yaml.safe_dump(hooks, sort_keys=False))


def propose(root: Path, tenant: str, walk_path: Path | None = None) -> dict:
    hooks = load_yaml(root / "workflows" / "skill-hooks.yaml")
    existing = load_yaml(root / "workflows" / "constraints.yaml")
    receipt = walk_path or (root / "tenants" / tenant / "audit" / "graph-walk.json")
    catalog = catalog_by_id(root / "catalog" / "modules.json")
    tdir = root / "tenants" / tenant
    drift = parse_evolution_drift(root / "agents")
    reds = load_walk_reds(receipt)
    enabled = enabled_modules(tdir)
    constraints = propose_constraints(reds, hooks)
    hook_diffs = propose_hook_diffs(enabled, catalog, hooks)
    reports = [d for d in drift if d.get("fallback_count")]
    return {
        "schema": "snowgloves.graph-upgrade.v1",
        "tenant": tenant,
        "dry_run": True,
        "reports": reports,
        "constraints_existing": existing.get("constraints") or [],
        "constraints_proposed": constraints,
        "hook_diffs": hook_diffs,
        "walk_reds": len(reds),
        "approval_mode": approval_mode(tdir),
        "note": "ingest.py does not mutate hooks; this path feeds the splitter.",
    }


def apply_proposal(root: Path, tenant: str, proposal: dict, *, write_hooks: bool) -> dict:
    cpath = root / "workflows" / "constraints.yaml"
    existing = load_yaml(cpath)
    merged = merge_constraints(existing.get("constraints") or [], proposal.get("constraints_proposed") or [])
    payload = {
        "version": existing.get("version") or "1",
        "description": existing.get("description") or "Derived routing constraints.",
        "constraints": merged,
    }
    cpath.parent.mkdir(parents=True, exist_ok=True)
    cpath.write_text(yaml.safe_dump(payload, sort_keys=False))
    result = {"constraints_written": str(cpath), "constraints_count": len(merged)}
    diffs = proposal.get("hook_diffs") or []
    tdir = root / "tenants" / tenant
    if not diffs:
        result["hooks"] = "none"
        return result
    if write_hooks:
        apply_hook_diffs(root / "workflows" / "skill-hooks.yaml", load_yaml(root / "workflows" / "skill-hooks.yaml"), diffs)
        result["hooks"] = "applied"
        return result
    ticket = queue_hook_ticket(tdir, tenant, diffs)
    result["hooks"] = "ticket"
    result["ticket_id"] = ticket["id"]
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Propose (or apply) graph learning-edge updates.")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--tenant", default="_demo")
    ap.add_argument("--walk", type=Path, default=None)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    proposal = propose(args.root, args.tenant, args.walk)
    applied = None
    if args.write:
        mode = proposal["approval_mode"]
        allow_hooks = mode in ALLOW_HOOK_WRITE
        applied = apply_proposal(args.root, args.tenant, proposal, write_hooks=allow_hooks)
        proposal["dry_run"] = False
        proposal["applied"] = applied
        if proposal.get("hook_diffs") and not allow_hooks:
            proposal["hook_gate"] = "approvals ticket (wide blast radius)"
    print(json.dumps(proposal, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

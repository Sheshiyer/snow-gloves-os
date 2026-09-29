#!/usr/bin/env python3
"""Walk the Chief of Staff skill graph with a machine-checkable loop in each native node.

Loop (Hanako): produce, check, correct until a program says GREEN. Retry that unit
only (max 3). Graph: named edges (agent+hook). inference-sh and Explee are pointers,
not fake GREEN. Silent default-fallback is RED unless the fixture expects it.

  python3 scripts/graph_walk.py
  python3 scripts/graph_walk.py --fixtures DIR --out PATH --scratch DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hermes import route  # noqa: E402

NATIVE_LOOP_UNITS = (
    "gtm-brief-synthesis",
    "tn-seed",
    "connector-gate",
    "sg-onboard",
)
MAX_ATTEMPTS = 3
GTM_REQUIRED = (
    "arm",
    "status",
    "companies_filters",
    "people_filters",
    "outreach_angle",
    "fit_criteria",
)
ONBOARD_HEADINGS = (
    "tenant",
    "owner",
    "company",
    "customer",
    "offer",
    "voice",
    "proof",
    "agents",
    "skills",
    "connectors",
    "runtimes",
    "preferences",
    "sources",
    "open questions",
)


def load_fixtures(fixtures_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(fixtures_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        data["_path"] = str(path)
        rows.append(data)
    return rows


def native_slug(skill: str) -> str | None:
    if skill.startswith("snowgloves:"):
        return skill.split(":", 1)[1]
    return None


def resolve_skill(skill: str, skills_root: Path) -> dict:
    slug = native_slug(skill)
    if slug:
        path = skills_root / "skills" / slug / "SKILL.md"
        if path.is_file():
            return {
                "skill": skill,
                "kind": "native",
                "path": str(path),
                "status": "ok",
            }
        return {
            "skill": skill,
            "kind": "native",
            "path": str(path),
            "status": "missing",
        }
    if skill.startswith("explee:") or skill.startswith("inference-sh/"):
        return {"skill": skill, "kind": "pointer", "status": "pointer"}
    local = skills_root / "skills" / skill / "SKILL.md"
    if local.is_file():
        return {
            "skill": skill,
            "kind": "native",
            "path": str(local),
            "status": "ok",
        }
    return {"skill": skill, "kind": "pointer", "status": "pointer"}


def routing_hit(matches: list[dict], expect: dict) -> bool:
    return any(
        m.get("agent") == expect.get("agent") and m.get("hook") == expect.get("hook")
        for m in matches
    )


def is_fallback(matches: list[dict]) -> bool:
    return any(m.get("hook") == "default-fallback" for m in matches)


def red(unit: str, reason: str, evidence, scope: str = "unit") -> dict:
    return {
        "UNIT": unit,
        "VERDICT": "RED",
        "REASON": reason,
        "EVIDENCE": evidence,
        "SCOPE": scope,
    }


def produce_gtm(dest: Path, broken: bool) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "brief-partner.json"
    data = {
        "arm": "partner",
        "status": "draft",
        "companies_filters": {"definition": "graph-walk"},
        "people_filters": {"job_titles": ["Founder"]},
        "outreach_angle": "walk-check",
        "fit_criteria": ["schema-keys"],
        "source_docs": ["graph-walk"],
    }
    if broken:
        data.pop("people_filters")
    path.write_text(json.dumps(data, indent=2))
    return path


def check_gtm(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "brief file missing"
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return False, f"brief not json: {exc}"
    missing = [k for k in GTM_REQUIRED if k not in data]
    if missing:
        return False, f"missing keys: {missing}"
    return True, "schema keys present"


def produce_tn_seed(dest: Path, broken: bool) -> Path:
    qdir = dest / "queue" / "r"
    qdir.mkdir(parents=True, exist_ok=True)
    path = qdir / "brief.md"
    body = "# seed brief\nstatus: needs-review\n" if not broken else "# seed brief\n"
    path.write_text(body)
    return path


def check_tn_seed(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "seed brief missing"
    text = path.read_text()
    if "needs-review" not in text:
        return False, "needs-review marker missing"
    return True, "queue brief present"


def produce_connector_gate(dest: Path, broken: bool) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "receipt.json"
    data = {
        "tenant": "_walk",
        "module": "ms-copywriting",
        "enabled": True,
        "disposition": "add",
        "verdict": "ALLOW",
    }
    if broken:
        data.pop("verdict")
    path.write_text(json.dumps(data, indent=2))
    return path


def check_connector_gate(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "gate receipt missing"
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return False, f"receipt not json: {exc}"
    needed = ("tenant", "enabled", "disposition", "verdict")
    missing = [k for k in needed if k not in data]
    if missing:
        return False, f"missing keys: {missing}"
    if data["verdict"] not in ("ALLOW", "REFUSE"):
        return False, f"bad verdict: {data['verdict']}"
    return True, "gate receipt ok"


def produce_sg_onboard(dest: Path, broken: bool) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "snowgloves-harvest.md"
    headings = list(ONBOARD_HEADINGS)
    if broken:
        headings = headings[:-3]
    path.write_text("".join(f"## {h.title()}\nFILL:\n\n" for h in headings))
    return path


def check_sg_onboard(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "harvest missing"
    text = path.read_text().lower()
    missing = [h for h in ONBOARD_HEADINGS if f"## {h}" not in text]
    if missing:
        return False, f"missing headings: {missing}"
    return True, "harvest headings present"


UNIT_IMPL = {
    "gtm-brief-synthesis": (produce_gtm, check_gtm),
    "tn-seed": (produce_tn_seed, check_tn_seed),
    "connector-gate": (produce_connector_gate, check_connector_gate),
    "sg-onboard": (produce_sg_onboard, check_sg_onboard),
}


def inner_loop(
    unit: str,
    scratch: Path,
    *,
    fail_attempts: int = 0,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict:
    """Produce / check / correct one unit. Do not rewind other units."""
    produce, check = UNIT_IMPL[unit]
    dest = scratch / unit
    attempts: list[dict] = []
    last_path: Path | None = None
    for n in range(1, max_attempts + 1):
        broken = n <= fail_attempts
        last_path = produce(dest, broken)
        ok, detail = check(last_path)
        attempts.append({"attempt": n, "ok": ok, "detail": detail})
        if ok:
            return {
                "unit": unit,
                "verdict": "GREEN",
                "attempts": n,
                "artifact": str(last_path),
                "check": detail,
                "log": attempts,
            }
    return {
        **red(
            unit,
            f"machine check failed after {max_attempts} attempts",
            attempts,
            scope="unit",
        ),
        "unit": unit,
        "verdict": "RED",
        "attempts": max_attempts,
        "artifact": str(last_path) if last_path else None,
        "log": attempts,
    }


def check_event(fx: dict, matches: list[dict], skill_rows: list[dict]) -> dict:
    expect = fx.get("expect") or {}
    want_fallback = bool(expect.get("fallback"))
    hit = routing_hit(matches, expect)
    fell = is_fallback(matches)
    silent = fell and not want_fallback
    missing_native = [s for s in skill_rows if s["kind"] == "native" and s["status"] == "missing"]
    pointers = [s for s in skill_rows if s["kind"] == "pointer"]
    reasons = []
    if not hit:
        reasons.append("route missed expected agent+hook")
    if silent:
        reasons.append("silent default-fallback")
    if missing_native:
        reasons.append("missing native skill")
    verdict = "GREEN" if not reasons else "RED"
    rec = {
        "id": fx.get("id"),
        "family": fx.get("family"),
        "task": fx.get("task"),
        "verdict": verdict,
        "expected": expect,
        "routing": matches,
        "skills": skill_rows,
        "fallback": fell,
        "silent_fallback": silent,
        "pointers": [p["skill"] for p in pointers],
    }
    if verdict == "RED":
        rec.update(
            red(
                f"event:{fx.get('id')}",
                "; ".join(reasons),
                {"expected": expect, "routing": matches, "missing_native": missing_native},
                scope="unit",
            )
        )
    return rec


def walk(
    *,
    fixtures_dir: Path,
    out_path: Path,
    scratch: Path,
    skills_root: Path,
    route_fn=None,
    sabotage: dict[str, int] | None = None,
) -> dict:
    route_fn = route_fn or route
    sabotage = sabotage or {}
    events = []
    overall = "GREEN"
    for fx in load_fixtures(fixtures_dir):
        task = fx.get("task") or {}
        matches = route_fn(task)
        skill_names: list[str] = []
        for m in matches:
            for s in m.get("skills") or []:
                if s not in skill_names:
                    skill_names.append(s)
        skill_rows = [resolve_skill(s, skills_root) for s in skill_names]
        rec = check_event(fx, matches, skill_rows)
        events.append(rec)
        if rec["verdict"] != "GREEN":
            overall = "RED"
    loops = []
    for unit in NATIVE_LOOP_UNITS:
        loop = inner_loop(unit, scratch, fail_attempts=int(sabotage.get(unit, 0)))
        loops.append(loop)
        if loop.get("verdict") != "GREEN":
            overall = "RED"
    receipt = {
        "schema": "snowgloves.graph-walk.v1",
        "verdict": overall,
        "events": events,
        "loops": loops,
    }
    try:
        json.dumps(receipt)
    except TypeError as exc:
        receipt = {
            "schema": "snowgloves.graph-walk.v1",
            "verdict": "RED",
            **red("receipt", f"receipt not json serializable: {exc}", str(type(exc))),
        }
        overall = "RED"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2))
    return receipt


def parse_sabotage(raw: str | None) -> dict[str, int]:
    if not raw:
        return {}
    out: dict[str, int] = {}
    for part in raw.split(","):
        if not part.strip():
            continue
        name, _, n = part.partition(":")
        out[name.strip()] = int(n or "99")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Walk the CoS skill graph (machine GREEN/RED).")
    ap.add_argument("--fixtures", type=Path, default=ROOT / "tests" / "fixtures" / "graph-walk")
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "tenants" / "_demo" / "audit" / "graph-walk.json",
    )
    ap.add_argument("--scratch", type=Path, default=None)
    ap.add_argument("--skills-root", type=Path, default=ROOT)
    ap.add_argument(
        "--sabotage",
        default="",
        help="test-only: unit:fail_attempts, e.g. gtm-brief-synthesis:3",
    )
    args = ap.parse_args(argv)
    scratch = args.scratch or (args.out.parent / "_walk_scratch")
    receipt = walk(
        fixtures_dir=args.fixtures,
        out_path=args.out,
        scratch=scratch,
        skills_root=args.skills_root,
        sabotage=parse_sabotage(args.sabotage),
    )
    print(json.dumps({"out": str(args.out), "verdict": receipt.get("verdict")}, indent=2))
    return 0 if receipt.get("verdict") == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())

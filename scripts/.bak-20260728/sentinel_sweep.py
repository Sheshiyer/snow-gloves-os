"""Sentinel — daily drift sweep.

Reads _audit/hermes-events.jsonl, computes per-agent signals:
  - fallback_count (default-fallback / no-match)
  - hook_diversity (#unique hooks used today)
  - skill_load (top 3 skills called)
  - escalation_count (technical or strategic escalations)

Appends a dated entry to each agent's agents/<slug>/EVOLUTION.md under
'Drift alerts (from sentinel)'.
"""
from __future__ import annotations
import json, os, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "_audit" / "hermes-events.jsonl"
AGENTS_DIR = ROOT / "agents"

def load_today():
    if not LOG.exists(): return []
    today = date.today().isoformat()
    rows = []
    for line in LOG.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("ts","").startswith(today):
            rows.append(r)
    return rows

def summarize(rows):
    per_agent = defaultdict(lambda: {
        "events": 0, "fallback": 0, "escalations": 0,
        "hooks": Counter(), "skills": Counter(),
    })
    for r in rows:
        for route in r.get("routing", []) or []:
            a = route.get("agent","chief-of-staff")
            s = per_agent[a]
            s["events"] += 1
            if route.get("hook") == "default-fallback":
                s["fallback"] += 1
            if route.get("escalation"):
                s["escalations"] += 1
            s["hooks"][route.get("hook","?")] += 1
            for sk in route.get("skills",[]) or []:
                s["skills"][sk] += 1
    return per_agent

def append_entry(slug: str, summary: dict, day: str):
    f = AGENTS_DIR / slug / "EVOLUTION.md"
    if not f.exists(): return False
    top_skills = ", ".join([k for k,_ in summary["skills"].most_common(3)]) or "—"
    entry = (
        f"\n### {day} — sentinel sweep\n"
        f"- events: {summary['events']}\n"
        f"- fallback_count: {summary['fallback']}\n"
        f"- escalations: {summary['escalations']}\n"
        f"- hook_diversity: {len(summary['hooks'])}\n"
        f"- top_skills: {top_skills}\n"
    )
    txt = f.read_text()
    if "## Drift alerts (from sentinel)" not in txt:
        txt += "\n## Drift alerts (from sentinel)\n"
    txt = txt.replace(
        "## Drift alerts (from sentinel)",
        "## Drift alerts (from sentinel)" + entry, 1)
    f.write_text(txt)
    return True

def run():
    rows = load_today()
    per = summarize(rows)
    day = date.today().isoformat()
    out = {"day": day, "events_seen": len(rows), "agents": {}}
    for slug in [p.name for p in AGENTS_DIR.iterdir() if p.is_dir()]:
        s = per.get(slug, {"events":0,"fallback":0,"escalations":0,
                           "hooks":Counter(),"skills":Counter()})
        append_entry(slug, s, day)
        out["agents"][slug] = {
            "events": s["events"], "fallback": s["fallback"],
            "escalations": s["escalations"],
            "hook_diversity": len(s["hooks"]),
            "top_skills": [k for k,_ in s["skills"].most_common(3)],
        }
    return out

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

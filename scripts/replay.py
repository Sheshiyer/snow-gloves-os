"""Re-route a logged event through the *current* skill-hooks.yaml.

Usage:
  scripts/replay.py --last 5
  scripts/replay.py --ts 2026-05-18T07:27:48
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hermes import route, LOG

def load():
    if not LOG.exists(): return []
    return [json.loads(l) for l in LOG.read_text().splitlines()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=1)
    ap.add_argument("--ts", help="match prefix of ts")
    a = ap.parse_args()
    rows = load()
    if a.ts: rows = [r for r in rows if r.get("ts","").startswith(a.ts)]
    rows = rows[-a.last:]
    out = []
    for r in rows:
        task = r.get("task") or r.get("event", {}).get("payload") or {}
        before = r.get("routing", [])
        after = route(task)
        out.append({"ts": r.get("ts"), "task": task,
                    "before": before, "after": after,
                    "changed": before != after})
    print(json.dumps(out, indent=2))

if __name__ == "__main__": main()

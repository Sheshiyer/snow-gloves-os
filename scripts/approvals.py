"""Approval inbox CLI.

approve/reject record who decided (``decided_by``) from ``--actor``, defaulting to the
``SNOWGLOVES_ACTOR`` environment variable (set per wing operator user, e.g. sg-coding).
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
from lib import paths
ROOT = paths.data_root()  # tenants live under the data root ($SNOWGLOVES_DATA, else this checkout)

def qfile(t): return ROOT / "tenants" / t / "approvals" / "pending.jsonl"
def hfile(t): return ROOT / "tenants" / t / "approvals" / "history.jsonl"

def load(t):
    f = qfile(t)
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

def save(t, rows):
    f = qfile(t); f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""))

def decide(t, ticket_id, status, reason="", actor=""):
    rows = load(t); hit = None
    rows2 = []
    for r in rows:
        if r["id"] == ticket_id:
            r["status"] = status; r["decided_at"] = int(time.time()); r["reason"] = reason
            r["decided_by"] = actor
            hit = r
        else:
            rows2.append(r)
    if not hit: return {"error": f"ticket not found: {ticket_id}"}
    save(t, rows2)
    hfile(t).open("a").write(json.dumps(hit) + "\n")
    return {"ok": True, "ticket": hit}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list","approve","reject"])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--id")
    ap.add_argument("--reason", default="")
    ap.add_argument("--actor", default=os.environ.get("SNOWGLOVES_ACTOR", ""),
                    help="recorded as decided_by on approve/reject (default: $SNOWGLOVES_ACTOR)")
    ap.add_argument("--data-root", help="instance data checkout (default: $SNOWGLOVES_DATA, else this checkout)")
    a = ap.parse_args(argv)
    if a.data_root:
        global ROOT
        ROOT = paths.data_root(a.data_root)
    if a.cmd == "list":
        print(json.dumps(load(a.tenant), indent=2)); return
    if not a.id: sys.exit("--id required")
    print(json.dumps(decide(a.tenant, a.id,
        "approved" if a.cmd == "approve" else "rejected", a.reason, a.actor), indent=2))

if __name__ == "__main__": main()

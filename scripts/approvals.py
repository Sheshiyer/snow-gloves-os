"""Approval inbox CLI."""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def qfile(t): return ROOT / "tenants" / t / "approvals" / "pending.jsonl"
def hfile(t): return ROOT / "tenants" / t / "approvals" / "history.jsonl"

def load(t):
    f = qfile(t)
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

def save(t, rows):
    f = qfile(t); f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""))

def decide(t, ticket_id, status, reason=""):
    rows = load(t); hit = None
    rows2 = []
    for r in rows:
        if r["id"] == ticket_id:
            r["status"] = status; r["decided_at"] = int(time.time()); r["reason"] = reason
            hit = r
        else:
            rows2.append(r)
    if not hit: return {"error": f"ticket not found: {ticket_id}"}
    save(t, rows2)
    hfile(t).open("a").write(json.dumps(hit) + "\n")
    return {"ok": True, "ticket": hit}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list","approve","reject"])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--id")
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    if a.cmd == "list":
        print(json.dumps(load(a.tenant), indent=2)); return
    if not a.id: sys.exit("--id required")
    print(json.dumps(decide(a.tenant, a.id,
        "approved" if a.cmd == "approve" else "rejected", a.reason), indent=2))

if __name__ == "__main__": main()

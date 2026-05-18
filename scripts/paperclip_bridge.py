"""Snow Gloves → Paperclip bridge.

Reads a routed decision (from Hermes), creates a Paperclip task in the right
lane, attaches the matched skills + audit ref, returns the issue id.
Supports --dry-run for environments without a running Paperclip instance.
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request, urllib.error
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONF = yaml.safe_load((ROOT / "config" / "snowgloves.yaml").read_text())
PC = CONF["paperclip"]
BASE = f"http://{PC['host']}:{PC['port']}"

def create_task(tenant: str, decision: dict, dry: bool = False) -> dict:
    routing = decision.get("routing", [decision])[0] if isinstance(decision.get("routing"), list) else decision
    agent = routing.get("agent", "chief-of-staff")
    skills = routing.get("skills", [])
    task = decision.get("task", {})
    payload = {
        "tenant": tenant,
        "lane": agent,
        "title": task.get("title", "(untitled snowgloves task)"),
        "tags": (task.get("tags") or []) + [f"snowgloves:hook:{routing.get('hook','default')}"],
        "brief": task.get("brief", ""),
        "skills": skills,
        "source": "snow-gloves-os",
        "hermes_audit_ts": decision.get("audit", {}).get("ts"),
    }
    if dry:
        return {"dry_run": True, "would_post": f"{BASE}/api/tasks", "payload": payload}
    try:
        req = urllib.request.Request(f"{BASE}/api/tasks",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=8).read())
    except (urllib.error.URLError, ConnectionError) as e:
        return {"error": str(e), "payload": payload, "hint": "use --dry-run if paperclip is not running"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--decision", help="path to JSON file with hermes /test/e2e response", required=False)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.decision:
        dec = json.loads(Path(a.decision).read_text())
    else:
        dec = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(create_task(a.tenant, dec, dry=a.dry_run), indent=2))

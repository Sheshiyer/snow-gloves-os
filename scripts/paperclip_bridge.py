"""Snow Gloves → Paperclip bridge (live by default, graceful fallback)."""
from __future__ import annotations
import argparse, json, os, sys, urllib.request, urllib.error
from pathlib import Path
import yaml
from lib.contract import extract_variable_contract

ROOT = Path(__file__).resolve().parent.parent
CONF = yaml.safe_load((ROOT / "config" / "snowgloves.yaml").read_text())
PC = CONF["paperclip"]
BASE = f"http://{PC['host']}:{PC['port']}"

# tenant → paperclip company resolution (extendable per tenant manifest)
DEFAULT_COMPANY = os.environ.get("SNOWGLOVES_DEFAULT_COMPANY", "")

def resolve_company(tenant: str) -> str | None:
    f = ROOT / "tenants" / tenant / "MANIFEST.yaml"
    if f.exists():
        try:
            m = yaml.safe_load(f.read_text()) or {}
            return m.get("paperclip", {}).get("company_id") or DEFAULT_COMPANY or None
        except Exception:
            pass
    return DEFAULT_COMPANY or None

def http_get(url, timeout=4):
    try:
        return json.loads(urllib.request.urlopen(url, timeout=timeout).read())
    except Exception as e:
        return {"_error": str(e)}

def ping() -> dict:
    return http_get(f"{BASE}/api/health") if False else http_get(f"{BASE}/")

def create_task(tenant: str, decision: dict, dry: bool = False) -> dict:
    routing_list = decision.get("routing") or [decision]
    primary = routing_list[0] if isinstance(routing_list, list) else routing_list
    agent = primary.get("agent", "chief-of-staff")
    skills = primary.get("skills", [])
    task = decision.get("task", {})
    variable_contract = decision.get("variable_contract") or extract_variable_contract(task)
    company = resolve_company(tenant)
    payload = {
        "tenant": tenant,
        "company_id": company,
        "lane": agent,
        "title": task.get("title", "(untitled snowgloves task)"),
        "tags": (task.get("tags") or []) + [f"snowgloves:hook:{primary.get('hook','default')}",
                                            f"snowgloves:tenant:{tenant}"],
        "brief": task.get("brief", ""),
        "skills": skills,
        "variable_contract": variable_contract,
        "all_routes": routing_list,
        "source": "snow-gloves-os",
        "hermes_audit_ts": decision.get("audit", {}).get("ts"),
    }
    if dry:
        return {"dry_run": True, "would_post": f"{BASE}/api/tasks", "payload": payload}
    # Live post with graceful fallback
    try:
        req = urllib.request.Request(f"{BASE}/api/tasks",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return {"ok": True, "response": json.loads(urllib.request.urlopen(req, timeout=8).read())}
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        # Queue locally for retry
        q = ROOT / "tenants" / tenant / "bridge_outbox.jsonl"
        q.parent.mkdir(parents=True, exist_ok=True)
        q.open("a").write(json.dumps(payload) + "\n")
        return {"ok": False, "queued": str(q), "error": str(e),
                "hint": "paperclip unreachable; payload queued for replay"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--decision", help="JSON file with hermes /test/e2e response")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ping", action="store_true")
    a = ap.parse_args()
    if a.ping: print(json.dumps(ping(), indent=2)); sys.exit(0)
    dec = json.loads(Path(a.decision).read_text()) if a.decision else json.loads(sys.stdin.read() or "{}")
    print(json.dumps(create_task(a.tenant, dec, dry=a.dry_run), indent=2))

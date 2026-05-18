"""Scope enforcement — block or require approval based on capabilities.yaml."""
from __future__ import annotations
from pathlib import Path
import yaml, json, time, secrets

ROOT = Path(__file__).resolve().parents[2]
CAPS = yaml.safe_load((ROOT / "connectors" / "g-stack" / "capabilities.yaml").read_text())

class ScopeViolation(Exception): ...
class ApprovalRequired(Exception):
    def __init__(self, ticket: dict): self.ticket = ticket; super().__init__(ticket["id"])

def lookup(connector: str, capability_id: str) -> dict | None:
    c = CAPS["connectors"].get(connector)
    if not c: return None
    for cap in c.get("capabilities", []):
        if cap["id"] == capability_id: return cap
    return None

def check(tenant: str, connector: str, capability_id: str, payload: dict | None = None) -> dict:
    cap = lookup(connector, capability_id)
    if not cap:
        raise ScopeViolation(f"{connector}.{capability_id} not in registry")
    if cap.get("approval") == "required" or cap.get("risk") == "high":
        return _queue_approval(tenant, connector, cap, payload or {})
    return {"ok": True, "capability": cap}

def _queue_approval(tenant: str, connector: str, cap: dict, payload: dict) -> dict:
    qdir = ROOT / "tenants" / tenant / "approvals"
    qdir.mkdir(parents=True, exist_ok=True)
    ticket = {
        "id": f"APR-{int(time.time())}-{secrets.token_hex(3)}",
        "tenant": tenant, "connector": connector,
        "capability": cap["id"], "risk": cap.get("risk"),
        "created_at": int(time.time()), "status": "pending",
        "payload": payload,
    }
    (qdir / "pending.jsonl").open("a").write(json.dumps(ticket) + "\n")
    raise ApprovalRequired(ticket)

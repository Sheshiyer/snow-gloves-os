"""Scope enforcement — block or require approval based on capabilities.yaml."""
from __future__ import annotations
from pathlib import Path
import yaml, json, time, secrets
from lib import paths

CODE_ROOT = paths.code_root()
ROOT = paths.data_root()  # approval queues: ROOT/tenants/<t>/approvals ($SNOWGLOVES_DATA, else this checkout)
CAPS = yaml.safe_load((CODE_ROOT / "connectors" / "g-stack" / "capabilities.yaml").read_text())

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

def queue_ticket(tenant: str, connector: str, capability_id: str, risk: str | None,
                 payload: dict, root: Path | None = None, kind: str | None = None) -> dict:
    """Append a pending ticket to <root>/tenants/<t>/approvals/pending.jsonl and return it."""
    qdir = (root or ROOT) / "tenants" / tenant / "approvals"
    qdir.mkdir(parents=True, exist_ok=True)
    ticket = {
        "id": f"APR-{int(time.time())}-{secrets.token_hex(3)}",
        "tenant": tenant, "connector": connector,
        "capability": capability_id, "risk": risk,
        "created_at": int(time.time()), "status": "pending",
        "payload": payload,
    }
    if kind:
        ticket["kind"] = kind
    with (qdir / "pending.jsonl").open("a") as f:
        f.write(json.dumps(ticket) + "\n")
    return ticket

def _queue_approval(tenant: str, connector: str, cap: dict, payload: dict) -> dict:
    raise ApprovalRequired(queue_ticket(tenant, connector, cap["id"], cap.get("risk"), payload))

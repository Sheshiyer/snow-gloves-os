"""G-Stack auth abstraction (stub).

Tenant-bound connector identities. Real impl would integrate Composio or a
secrets vault. This stub only validates shape + persists bindings to disk.
"""
from __future__ import annotations
import json, os, secrets, time
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]

def _store(tenant: str) -> Path:
    p = ROOT / "tenants" / tenant / "connectors"
    p.mkdir(parents=True, exist_ok=True)
    return p

def bind(tenant: str, connector: str, auth_type: Literal["oauth2","api_key"], secret: str | None = None) -> dict:
    rec = {
        "tenant": tenant,
        "connector": connector,
        "auth_type": auth_type,
        "binding_id": secrets.token_hex(8),
        "secret_ref": "vault://" + secrets.token_hex(8) if secret else None,
        "created_at": int(time.time()),
        "status": "active",
    }
    (_store(tenant) / f"{connector}.json").write_text(json.dumps(rec, indent=2))
    return rec

def list_bindings(tenant: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in _store(tenant).glob("*.json")]

def revoke(tenant: str, connector: str) -> bool:
    f = _store(tenant) / f"{connector}.json"
    if not f.exists(): return False
    rec = json.loads(f.read_text()); rec["status"] = "revoked"
    f.write_text(json.dumps(rec, indent=2)); return True

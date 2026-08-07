"""G-Stack inbound webhook → Hermes publish.

Verifies a simple HMAC signature, normalizes the payload into a Snow Gloves
event envelope, and POSTs to Hermes /publish on port 4100.
"""
from __future__ import annotations
import hmac, hashlib, json, os, sys, time, urllib.request
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONF = yaml.safe_load((ROOT / "config" / "snowgloves.yaml").read_text())
HERMES = f"http://{CONF['hermes']['host']}:{CONF['hermes']['port']}/publish"

def verify(secret: str, body: bytes, signature: str) -> bool:
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, signature or "")

def normalize(tenant: str, connector: str, capability: str, payload: dict) -> dict:
    return {
        "channel": CONF["hermes"]["channel"],
        "event": {
            "tenant": tenant,
            "connector": connector,
            "capability": capability,
            "received_at": int(time.time()),
            "payload": payload,
        }
    }

def emit(envelope: dict) -> dict:
    req = urllib.request.Request(HERMES,
        data=json.dumps(envelope).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=5).read())

def handle(tenant: str, connector: str, capability: str, body: bytes, signature: str, secret: str) -> dict:
    if not verify(secret, body, signature):
        return {"ok": False, "error": "bad signature"}
    payload = json.loads(body or b"{}")
    return {"ok": True, "result": emit(normalize(tenant, connector, capability, payload))}

if __name__ == "__main__":
    # Smoke: simulate an inbound PMS booking event end-to-end (requires Hermes running)
    secret = "demo-secret"
    body = json.dumps({"booking_id": "BK-1001", "amount": 320, "currency": "USD"}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    print(json.dumps(handle("_demo", "pms_generic", "pms.read_bookings", body, sig, secret), indent=2))

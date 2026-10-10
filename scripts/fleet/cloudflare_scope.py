#!/usr/bin/env python3
"""Read-only company Cloudflare guard using a named Wrangler login. Never emits tokens."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

OVERRIDES = (
    "CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "CLOUDFLARE_API_KEY", "CF_API_KEY",
    "CLOUDFLARE_EMAIL", "CF_EMAIL", "CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID",
    "WRANGLER_LOG", "WRANGLER_LOG_SANITIZE",
)
DENIED = ("thoughtseed.space", "tryambakam.space", "heyzack.ai")


class ScopeError(ValueError):
    pass


def validate_target(target: dict) -> None:
    for field in ("account_id", "zone_id"):
        if not re.fullmatch(r"[a-f0-9]{32}", str(target.get(field, ""))):
            raise ScopeError(f"invalid {field}")
    zone = target.get("zone", "")
    hostname = target.get("hostname", "")
    if not isinstance(zone, str) or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", zone):
        raise ScopeError("invalid zone")
    if (not isinstance(hostname, str) or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", hostname)
            or not hostname.endswith("." + zone)):
        raise ScopeError("hostname must be beneath the pinned zone")
    if any(zone == d or zone.endswith("." + d) for d in DENIED):
        raise ScopeError("denied company-gateway domain")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", str(target.get("profile", ""))):
        raise ScopeError("invalid named profile")
    if target["profile"] in ("default", "personal"):
        raise ScopeError("personal/default profiles are refused")
    if not isinstance(target.get("identity"), str) or "@" not in target["identity"]:
        raise ScopeError("pinned identity required")
    if not isinstance(target.get("profile_cwd"), str) or not Path(target["profile_cwd"]).is_absolute():
        raise ScopeError("absolute profile binding directory required")


def validate_identity(target: dict, identity: dict) -> None:
    if not identity.get("loggedIn") or identity.get("email") != target["identity"]:
        raise ScopeError("authenticated identity mismatch")
    if target["account_id"] not in [a.get("id") for a in identity.get("accounts", [])]:
        raise ScopeError("pinned account absent from authenticated membership")


def validate_zone(target: dict, body: dict) -> None:
    zone = body.get("result") or {}
    if not body.get("success"):
        raise ScopeError("zone API read failed")
    if (zone.get("id"), zone.get("name"), (zone.get("account") or {}).get("id"), zone.get("status")) != (
        target["zone_id"], target["zone"], target["account_id"], "active"
    ):
        raise ScopeError("active zone/account binding mismatch")


def wrangler_json(args: list[str]) -> dict:
    env = dict(os.environ)
    for name in OVERRIDES:
        env.pop(name, None)
    try:
        proc = subprocess.run(["wrangler", *args], env=env, capture_output=True, text=True, timeout=45)
        if proc.returncode:
            raise ScopeError("Wrangler authentication read failed; credential output suppressed")
        result = json.loads(proc.stdout)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ScopeError("Wrangler read unavailable or malformed; raw output suppressed") from exc


def profile_token(args: list[str]) -> str:
    credentials = wrangler_json(args)
    token = credentials.get("token") or credentials.get("access_token")
    if not isinstance(token, str) or not token:
        raise ScopeError("named profile token unavailable")
    return token


def check(target: dict) -> dict:
    validate_target(target)
    # `wrangler whoami` has no --profile flag: it reports the profile bound to profile_cwd. The token
    # comes from the named profile, so prove both are the same login before trusting the identity.
    identity = wrangler_json(["whoami", "--cwd", target["profile_cwd"], "--json"])
    validate_identity(target, identity)
    token = profile_token(["auth", "token", "--profile", target["profile"], "--json"])
    bound = profile_token(["auth", "token", "--cwd", target["profile_cwd"], "--json"])
    if not hmac.compare_digest(token.encode(), bound.encode()):
        raise ScopeError("profile_cwd is not bound to the named profile; identity and token differ")
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/zones/" + target["zone_id"],
        headers={"Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = json.load(response)
    except (OSError, ValueError) as exc:
        raise ScopeError("authenticated zone read failed; raw output suppressed") from exc
    validate_zone(target, body)
    return {"ok": True, "evidence_level": "authenticated-read", "resources_mutated": False,
            **{k: target[k] for k in ("profile", "identity", "account_id", "zone_id", "zone", "hostname")}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path, help="private JSON target pins")
    args = parser.parse_args(argv)
    try:
        target = json.loads(args.target.read_text())
        if not isinstance(target, dict):
            raise ScopeError("target must be an object")
        print(json.dumps(check(target), indent=2))
        return 0
    except (ScopeError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc) if isinstance(exc, ScopeError) else "invalid private target"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

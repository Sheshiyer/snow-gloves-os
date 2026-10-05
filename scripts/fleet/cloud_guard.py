#!/usr/bin/env python3
"""Cloud gateway guard: prove we are about to touch the right AWS account and Cloudflare zone.

Every infra command (scripts/fleet/cloud_gateway.sh) runs this first. It reads the
`cloud_gateway:` block of fleet.yaml ($SNOWGLOVES_DATA/fleet.yaml when set) and refuses
to continue unless:

  boundary    the offline fleet-boundary check passes (doctor.check_fleet_boundary)
  aws         `aws sts get-caller-identity --profile <aws_profile>` returns aws_account_id
  cloudflare  the API token (macOS Keychain, service cf_token_keychain) can read cf_zone_id,
              that zone is named `zone`, and it belongs to cf_account_id

    python3 scripts/fleet/cloud_guard.py check [boundary|aws|cloudflare|all]
    python3 scripts/fleet/cloud_guard.py tfvars aws|cloudflare     # JSON for tofu -var-file
    python3 scripts/fleet/cloud_guard.py env                       # shell exports for cloud_gateway.sh (no secrets)

Never prints the token. Account and zone ids are not secrets but stay in the private data repo.
Exit 0 when every requested check passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import paths  # noqa: E402

_spec = importlib.util.spec_from_file_location("fleet_doctor", Path(__file__).with_name("doctor.py"))
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

CF_API = "https://api.cloudflare.com/client/v4"
DEFAULT_CF_KEYCHAIN = "snowgloves-cloudflare"
DEFAULT_TS_KEYCHAIN = "snowgloves-tailscale-authkey"


def load_fleet(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("cloud_gateway"), dict):
        raise SystemExit(f"{path}: no cloud_gateway block")
    return data


run = doctor.run  # (returncode | None, stdout, stderr); tests stub this name


def keychain_secret(service: str) -> str | None:
    if not shutil.which("security"):
        return None
    rc, out, _ = run(["security", "find-generic-password", "-s", service, "-w"], timeout=10)
    return (out.strip() or None) if rc == 0 else None


def cf_get(path: str, token: str, timeout: float = 15.0) -> tuple[int, dict]:
    req = urllib.request.Request(CF_API + path, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https host
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, {"errors": [{"message": str(getattr(exc, "reason", exc))}]}


# ---------------------------------------------------------------- checks

def check_boundary(fleet: dict) -> tuple[bool, str]:
    c = doctor.check_fleet_boundary(fleet)
    return c["ok"], c["detail"]


def check_aws(cg: dict) -> tuple[bool, str]:
    profile, want = str(cg.get("aws_profile") or ""), str(cg.get("aws_account_id") or "")
    if not shutil.which("aws"):
        return False, "aws CLI not installed"
    rc, out, err = run(["aws", "sts", "get-caller-identity", "--profile", profile, "--output", "json"], timeout=30)
    if rc != 0:
        first = (err.strip().splitlines() or ["no output"])[0]
        return False, f"profile {profile}: sts failed ({first}); run `aws sso login --profile {profile}`"
    try:
        got = str(json.loads(out).get("Account") or "")
    except ValueError:
        return False, f"profile {profile}: sts output is not JSON"
    if got != want:
        return False, f"profile {profile} is account {got or '?'}, fleet.yaml pins {want}; refusing"
    return True, f"profile {profile} -> account {got}"


def check_cloudflare(cg: dict, token: str | None = None) -> tuple[bool, str]:
    service = str(cg.get("cf_token_keychain") or DEFAULT_CF_KEYCHAIN)
    token = token or keychain_secret(service)
    if not token:
        return False, f"no Cloudflare token in Keychain service {service}"
    zone_id, zone, account = (str(cg.get(k) or "") for k in ("cf_zone_id", "zone", "cf_account_id"))
    status, body = cf_get(f"/zones/{zone_id}", token)
    if status != 200 or not body.get("success"):
        msg = "; ".join(e.get("message", "") for e in body.get("errors") or []) or f"http {status}"
        return False, f"token cannot read zone {zone_id}: {msg}"
    result = body.get("result") or {}
    got_name = str(result.get("name") or "")
    got_account = str((result.get("account") or {}).get("id") or "")
    if got_name.lower() != zone.lower():
        return False, f"zone {zone_id} is {got_name}, fleet.yaml says {zone}; refusing"
    if got_account != account:
        return False, f"zone {zone} belongs to account {got_account or '?'}, fleet.yaml pins {account}; refusing"
    return True, f"token reads {zone} in account {account} (Keychain {service})"


# ---------------------------------------------------------------- tofu variables

def tfvars(fleet: dict, stack: str) -> dict:
    cg = fleet["cloud_gateway"]
    name = str(cg.get("name") or "snowgloves-gw")
    common = {"name": name, "aws_region": str(cg["region"]), "aws_profile": cg["aws_profile"]}
    if stack == "aws":
        out = {
            **common,
            "instance_type": cg.get("instance_type") or "t4g.medium",
            "volume_size_gb": int(cg.get("volume_size_gb") or 40),
            "omniroute_version": str(cg.get("omniroute_version") or "3.8.50"),
            "tailnet_hostname": cg.get("tailnet_hostname") or name,
            "budget_alarm_usd": int(cg.get("budget_alarm_usd") or 60),
            "alarm_email": cg.get("alarm_email") or "",
        }
    elif stack == "cloudflare":
        out = {
            **common,
            "cf_account_id": cg["cf_account_id"],
            "cf_zone_id": cg["cf_zone_id"],
            "zone": cg["zone"],
            "hostname": cg["hostname"],
            "allow_ips": [str(i) for i in cg.get("allow_ips") or []],
            "access_emails": [str(e) for e in cg.get("access_emails") or []],
            "deny_domains": [str(d) for d in cg.get("deny_domains") or []],
        }
    else:
        raise SystemExit(f"unknown stack {stack!r} (aws or cloudflare)")
    return out


def shell_env(fleet: dict) -> str:
    """Non-secret values cloud_gateway.sh needs, as `export K=V` lines."""
    cg = fleet["cloud_gateway"]
    name = str(cg.get("name") or "snowgloves-gw")
    account = str(cg["aws_account_id"])
    values = {
        "SG_NAME": name,
        "SG_REGION": str(cg["region"]),
        "SG_PROFILE": str(cg["aws_profile"]),
        "SG_ACCOUNT": account,
        "SG_STATE_BUCKET": str(cg.get("state_bucket") or f"{name}-tfstate-{account}"),
        "SG_CF_KEYCHAIN": str(cg.get("cf_token_keychain") or DEFAULT_CF_KEYCHAIN),
        "SG_TS_KEYCHAIN": str(cg.get("tailscale_authkey_keychain") or DEFAULT_TS_KEYCHAIN),
        "SG_HOSTNAME": str(cg.get("hostname") or ""),
    }
    return "".join(f"export {k}={shlex.quote(v)}\n" for k, v in values.items())


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fleet", type=Path, default=None, help="fleet.yaml (default: $SNOWGLOVES_DATA/fleet.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="run guard checks")
    c.add_argument("what", nargs="?", default="all", choices=("boundary", "aws", "cloudflare", "all"))
    t = sub.add_parser("tfvars", help="print tofu variables for a stack as JSON")
    t.add_argument("stack", choices=("aws", "cloudflare"))
    sub.add_parser("env", help="print shell exports for cloud_gateway.sh (boundary-checked, no secrets)")
    args = ap.parse_args(argv)

    fleet = load_fleet((args.fleet or paths.fleet_file()).resolve())
    cg = fleet["cloud_gateway"]
    if args.cmd in ("tfvars", "env"):
        ok, detail = check_boundary(fleet)
        if not ok:
            print(f"FAIL boundary   {detail}", file=sys.stderr)
            return 1
        print(json.dumps(tfvars(fleet, args.stack), indent=2) if args.cmd == "tfvars" else shell_env(fleet), end="\n" if args.cmd == "tfvars" else "")
        return 0

    plan = {"boundary": ["boundary"], "aws": ["boundary", "aws"],
            "cloudflare": ["boundary", "cloudflare"], "all": ["boundary", "aws", "cloudflare"]}[args.what]
    ok_all = True
    for name in plan:
        ok, detail = {"boundary": lambda: check_boundary(fleet), "aws": lambda: check_aws(cg),
                      "cloudflare": lambda: check_cloudflare(cg)}[name]()
        ok_all = ok_all and ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:<10} {detail}")
        if not ok and name == "boundary":
            break  # never touch an account when the inventory itself is out of bounds
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())

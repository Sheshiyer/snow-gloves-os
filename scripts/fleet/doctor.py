#!/usr/bin/env python3
"""Fleet doctor: is this Mac mini wired as the wing that fleet.yaml says it is?

Read-only. Stdlib plus pyyaml. Never prints config file contents, keys, or IPs.

    python3 scripts/fleet/doctor.py                  # wing from SNOWGLOVES_NODE or the hostname
    python3 scripts/fleet/doctor.py --wing coding    # override (authoring seat checking a wing)
    python3 scripts/fleet/doctor.py --json           # machine-readable list of checks

Each check is {name, ok, detail, critical}. Exit 0 when every critical check passes
(node profile, gateway local-or-fleet, tenants registered, and fleet-boundary when fleet.yaml
has a cloud_gateway block); exit 1 otherwise.
Non-critical checks print as WARN and never change the exit code.

fleet.yaml, nodes/ and tenants/ are read from $SNOWGLOVES_DATA when it is set (the
private data checkout), else from this checkout; nodes/ falls back to the templates here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import paths  # noqa: E402
from lib.gateway_url import parse_gateway_url  # noqa: E402
SCHEMA = "snowgloves.fleet-doctor.v1"
DEFAULT_GATEWAY_PORT = 20128
DEFAULT_HERMES_PORT = 4100
CRITICAL = ("node-profile", "gateway", "tenants")  # fleet-boundary is critical only with a cloud_gateway block
RUNTIMES = ("claude", "codex", "grok", "opencode")
# Candidate config files per runtime, relative to --home. First one that exists wins.
RUNTIME_CONFIGS = {
    "claude": (".claude/settings.json", ".claude.json"),
    "codex": (".codex/config.toml",),
    "grok": (".grok/config.toml", ".grok/settings.json"),
    "opencode": (".config/opencode/opencode.json", ".config/opencode/opencode.jsonc"),
}
TAILSCALE_APP = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


# ---------------------------------------------------------------- helpers

def check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "critical": name in CRITICAL}


def run(cmd: list[str], timeout: float = 5.0) -> tuple[int | None, str, str]:
    """Run a command; never raise. rc is None when the command could not run."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", str(exc)


def load_yaml(path: Path) -> tuple[object, str | None]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), None
    except (OSError, yaml.YAMLError) as exc:
        return None, str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__


def norm(name: object) -> str:
    s = str(name or "").strip().lower()
    for ch in ("’", "‘", "'"):
        s = s.replace(ch, "")
    if s.endswith(".local"):
        s = s[: -len(".local")]
    return "-".join(s.split())


def detect_hostname() -> str:
    rc, out, _ = run(["scutil", "--get", "ComputerName"], timeout=3)
    name = out.strip() if rc == 0 else ""
    return name or socket.gethostname()


def probe_http(url: str, timeout: float) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed, non-secret URLs)
            code = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(code) < 400, f"http {code}"
    except urllib.error.HTTPError as exc:
        return False, f"http {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"unreachable ({reason})"


def probe_tcp(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def find_tailscale() -> str | None:
    exe = shutil.which("tailscale")
    if exe:
        return exe
    return TAILSCALE_APP if Path(TAILSCALE_APP).exists() else None


def wings_of(fleet: dict | None) -> dict:
    wings = (fleet or {}).get("wings") or {}
    return wings if isinstance(wings, dict) else {}


def gateway_of(fleet: dict | None) -> tuple[str, int]:
    gw = (fleet or {}).get("gateway") or {}
    if not isinstance(gw, dict):
        gw = {}  # a malformed gateway entry reads as "no gateway" instead of crashing the doctor
    try:
        port = int(gw.get("port") or DEFAULT_GATEWAY_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_GATEWAY_PORT
    return str(gw.get("url") or "").rstrip("/"), port


def gateway_field(fleet: dict | None, key: str) -> str:
    gw = (fleet or {}).get("gateway") or {}
    return str(gw.get(key) or "").rstrip("/") if isinstance(gw, dict) else ""


def url_parts(url: str) -> tuple[str, str]:
    """(scheme, host) of a URL, host lowercased; empty strings when it does not parse."""
    scheme, host, _ = parse_gateway_url(url)
    return scheme or "", (host or "").lower()


def under(host: str, domain: str) -> bool:
    host, domain = host.lower().rstrip("."), domain.lower().strip(".")
    return bool(domain) and (host == domain or host.endswith("." + domain))


# ---------------------------------------------------------------- wing identity

def resolve_wing(fleet: dict | None, override: str | None, hostname: str) -> tuple[str, str]:
    """Return (wing, source). source is one of --wing, SNOWGLOVES_NODE, hostname."""
    if override:
        return override.strip(), "--wing"
    env = os.environ.get("SNOWGLOVES_NODE", "").strip()
    if env:
        return env, "SNOWGLOVES_NODE"
    h = norm(hostname)
    for key, w in wings_of(fleet).items():
        w = w or {}
        names = {norm(key), norm(w.get("hostname")), norm(w.get("overlay"))} - {""}
        if h and h in names:
            return str(key), "hostname"
    return "", "hostname"


def check_wing(fleet: dict | None, wing: str, source: str, hostname: str) -> dict:
    if not fleet:
        if wing:
            return check("wing", False, f"fleet.yaml missing or unparseable; wing={wing} via {source} cannot be checked against the inventory")
        return check("wing", False, "fleet.yaml missing or unparseable; cannot identify this wing")
    wings = wings_of(fleet)
    known = ", ".join(sorted(wings)) or "none"
    if not wing:
        seat = (fleet.get("authoring_seat") or {}) if isinstance(fleet.get("authoring_seat"), dict) else {}
        if norm(seat.get("hostname")) and norm(seat.get("hostname")) == norm(hostname):
            return check("wing", False, f"host '{hostname}' is the authoring seat ({seat.get('role', 'staging')}), not a wing; pass --wing <wing> to inspect a wing (wings: {known})")
        return check("wing", False, f"host '{hostname}' matches no wing in fleet.yaml; set SNOWGLOVES_NODE=<wing> or pass --wing (wings: {known})")
    if wing not in wings:
        return check("wing", False, f"'{wing}' (via {source}) is not a wing in fleet.yaml (wings: {known})")
    w = wings[wing] or {}
    expected = {norm(w.get("hostname")), norm(w.get("overlay")), norm(wing)} - {""}
    if source == "hostname" or norm(hostname) in expected:
        return check("wing", True, f"wing={wing} via {source}; hostname '{hostname}'")
    return check("wing", False, f"wing={wing} via {source}; hostname '{hostname}' does not match {w.get('hostname') or wing} (authoring seat, or rename this mini)")


# ---------------------------------------------------------------- checks

def check_node_profile(root: Path, wing: str) -> tuple[dict, dict | None]:
    nodes = root / "nodes"
    if not nodes.is_dir():  # a data checkout without nodes/ uses the templates shipped with the code
        nodes = ROOT / "nodes"
    if not wing:
        available = ", ".join(sorted(p.parent.name for p in nodes.glob("*/node.yaml"))) or "none"
        return check("node-profile", False, f"wing unknown; cannot pick nodes/<wing>/node.yaml (available: {available})"), None
    path = nodes / wing / "node.yaml"
    rel = f"nodes/{wing}/node.yaml"
    if not path.exists():
        return check("node-profile", False, f"{rel} missing"), None
    data, err = load_yaml(path)
    if err:
        return check("node-profile", False, f"{rel} does not parse: {err}"), None
    if not isinstance(data, dict):
        return check("node-profile", False, f"{rel} is not a mapping"), None
    declared = data.get("wing") or data.get("node") or data.get("id")
    if declared and str(declared) != wing:
        return check("node-profile", False, f"{rel} declares wing '{declared}', expected '{wing}'"), data
    return check("node-profile", True, f"{rel} parsed ({len(data)} keys)"), data


def check_tailscale() -> dict:
    exe = find_tailscale()
    if not exe:
        return check("tailscale", False, "not installed")
    rc, out, _ = run([exe, "status", "--json"], timeout=5)
    if rc != 0:
        return check("tailscale", False, f"installed; `tailscale status` failed (rc={rc})")
    try:
        status = json.loads(out or "{}")
    except json.JSONDecodeError:
        return check("tailscale", False, "installed; status output is not JSON")
    state = status.get("BackendState") if isinstance(status, dict) else None
    me = (status.get("Self") or {}) if isinstance(status, dict) else {}
    host = me.get("HostName") or ""
    if state == "Running":
        return check("tailscale", True, f"running{' as ' + host if host else ''}")
    return check("tailscale", False, f"installed; backend state {state or 'unknown'} (run `tailscale up`)")


def check_gateway(fleet: dict | None, timeout: float) -> dict:
    fleet_url, port = gateway_of(fleet)
    local_url = f"http://127.0.0.1:{port}"
    ok_any = False
    parts = []
    lan_url = gateway_field(fleet, "lan_url")
    tailnet_url = gateway_field(fleet, "tailnet_url")
    targets = ([("fleet", fleet_url)] + ([("tailnet", tailnet_url)] if tailnet_url else [])
               + ([("lan", lan_url)] if lan_url else []) + [("local", local_url)])
    for label, base in targets:
        if not base:
            parts.append(f"{label}: no gateway.url in fleet.yaml")
            continue
        ok, detail = probe_http(f"{base}/healthz", timeout)
        ok_any = ok_any or ok
        parts.append(f"{label} {base}/healthz: {'ok' if ok else 'down'} ({detail})")
    return check("gateway", ok_any, "; ".join(parts))


def check_fleet_boundary(fleet: dict | None) -> dict:
    """Offline guard that a cloud gateway stays inside its own domain and accounts.

    Reads fleet.yaml cloud_gateway: {hostname, zone, aws_profile, aws_account_id, cf_account_id,
    cf_zone_id, deny_domains, deny_aws_profiles}. Every gateway URL host must sit under `zone`
    and under none of `deny_domains`; the AWS profile must be named and not denied. Live account
    checks (sts identity, Cloudflare zone ownership) are scripts/fleet/cloud_guard.py.
    """
    cg = (fleet or {}).get("cloud_gateway") if isinstance(fleet, dict) else None
    if cg is None:  # absent, or a key whose children are all commented out (a staged block)
        return check("fleet-boundary", True, "no cloud_gateway in fleet.yaml; nothing to guard")
    if not isinstance(cg, dict):
        c = check("fleet-boundary", False, "cloud_gateway is not a mapping")
        c["critical"] = True
        return c
    problems = []
    zone = str(cg.get("zone") or "").strip()
    hostname = str(cg.get("hostname") or "").strip().lower()
    deny = [str(d).strip() for d in (cg.get("deny_domains") or []) if str(d).strip()]
    if not zone or zone.startswith("<"):
        problems.append("cloud_gateway.zone unset")
    if not hostname or hostname.startswith("<"):
        problems.append("cloud_gateway.hostname unset")
    elif zone and not under(hostname, zone):
        problems.append(f"hostname {hostname} is not under zone {zone}")
    url = gateway_field(fleet, "url")
    scheme, host = url_parts(url)
    if gateway_field(fleet, "kind") == "cloud":
        if scheme != "https":
            problems.append(f"gateway.url must be https for a cloud gateway (got {url or 'nothing'})")
        if hostname and host != hostname:
            problems.append(f"gateway.url host {host or '?'} differs from cloud_gateway.hostname {hostname}")
    hosts = {h for h in (host, hostname, zone.lower(), url_parts(gateway_field(fleet, "tailnet_url"))[1]) if h}
    for h in sorted(hosts):
        for d in deny:
            if under(h, d) or d.lower() in h:
                problems.append(f"{h} matches denied domain {d}")
    profile = str(cg.get("aws_profile") or "").strip()
    deny_profiles = {"default"} | {str(p) for p in (cg.get("deny_aws_profiles") or [])}
    if not profile:
        problems.append("cloud_gateway.aws_profile unset (a named profile is required)")
    elif profile in deny_profiles:
        problems.append(f"aws_profile {profile} is denied")
    for key in ("region", "aws_account_id", "cf_account_id", "cf_zone_id"):
        if not str(cg.get(key) or "").strip() or str(cg.get(key)).startswith("<"):
            problems.append(f"cloud_gateway.{key} unset")
    account = cg.get("aws_account_id")
    if account and not str(account).startswith("<") and not (
            isinstance(account, str) and re.fullmatch(r"\d{12}", account.strip())):
        # an unquoted id parses as an int (octal with a leading 0), which never equals STS's string
        problems.append("cloud_gateway.aws_account_id must be a quoted 12-digit string")
    detail = "; ".join(problems) if problems else (
        f"{hostname} under {zone}; profile {profile}; {len(deny)} denied domains clear")
    c = check("fleet-boundary", not problems, detail)
    c["critical"] = True
    return c


def check_remote_management() -> dict:
    rc, _, _ = run(["pgrep", "-x", "ARDAgent"], timeout=3)
    if rc == 0:
        return check("remote-management", True, "on (ARDAgent running)")
    rc2, _, _ = run(["launchctl", "print", "system/com.apple.screensharing"], timeout=3)
    if rc2 == 0:
        return check("remote-management", True, "on (com.apple.screensharing loaded)")
    if rc is None and rc2 is None:
        return check("remote-management", False, "unknown (pgrep and launchctl unavailable)")
    return check("remote-management", False, "off (no ARDAgent; screen sharing not loaded)")


def check_ssh() -> dict:
    rc, out, err = run(["systemsetup", "-getremotelogin"], timeout=5)
    text = f"{out}\n{err}".lower()
    if rc == 0 and "remote login: on" in text:
        return check("ssh", True, "on (systemsetup)")
    if rc == 0 and "remote login: off" in text:
        return check("ssh", False, "off (systemsetup)")
    if probe_tcp("127.0.0.1", 22):
        return check("ssh", True, "on (port 22 open; systemsetup needs sudo for detail)")
    return check("ssh", False, "unknown (systemsetup needs sudo; port 22 closed)")


def check_hermes(fleet: dict | None, wing: str) -> dict:
    wings = wings_of(fleet)
    owner, port = None, DEFAULT_HERMES_PORT
    for key, w in wings.items():
        for svc in (w or {}).get("services") or []:
            if isinstance(svc, dict) and svc.get("id") == "hermes":
                owner = str(key)
                try:
                    port = int(svc.get("port") or port)
                except (TypeError, ValueError):
                    pass
    host = "127.0.0.1"
    if owner and owner != wing:
        w = wings.get(owner) or {}
        host = str(w.get("overlay") or w.get("hostname") or host)
    ok = probe_tcp(host, port)
    hosted = f" (hosted by the {owner} wing)" if owner else ""
    return check("hermes", ok, f"{host}:{port} {'reachable' if ok else 'not reachable'}{hosted}")


def _slug(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("slug") or item.get("id") or "")
    return str(item or "")


def check_tenants(root: Path) -> dict:
    reg = root / "tenants" / "_registry.yaml"
    if not reg.exists():
        return check("tenants", False, "tenants/_registry.yaml missing")
    data, err = load_yaml(reg)
    if err:
        return check("tenants", False, f"tenants/_registry.yaml does not parse: {err}")
    raw = (data or {}).get("tenants") if isinstance(data, dict) else None
    slugs = [s for s in (_slug(x) for x in (raw or [])) if s and not s.startswith("_")]  # `_demo` = fixture
    missing = [s for s in slugs if not (root / "tenants" / s / "MANIFEST.yaml").exists()]
    if missing:
        return check("tenants", False, f"{len(missing)} of {len(slugs)} registered tenants lack MANIFEST.yaml: {', '.join(missing)}")
    return check("tenants", True, f"{len(slugs)} registered, all have MANIFEST.yaml")


def expected_runtimes(node: dict | None) -> list[str] | None:
    if not isinstance(node, dict):
        return None
    rts = node.get("runtimes")
    if isinstance(rts, dict):
        return [str(k) for k in rts]
    if isinstance(rts, list):
        return [_slug(r) if isinstance(r, dict) else str(r) for r in rts]
    return None


def check_runtimes(home: Path, fleet: dict | None, node: dict | None) -> list[dict]:
    fleet_url, port = gateway_of(fleet)
    needles = {fleet_url, gateway_field(fleet, "tailnet_url"), f"127.0.0.1:{port}", f"localhost:{port}"} - {""}
    expected = expected_runtimes(node)
    out = []
    for rt in RUNTIMES:
        name = f"runtime-{rt}"
        if expected is not None and rt not in expected:
            out.append(check(name, True, "not in node.runtimes; skipped"))
            continue
        found = next((rel for rel in RUNTIME_CONFIGS[rt] if (home / rel).exists()), None)
        if not found:
            out.append(check(name, False, f"no config at ~/{RUNTIME_CONFIGS[rt][0]}"))
            continue
        try:
            text = (home / found).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            out.append(check(name, False, f"~/{found} present but unreadable"))
            continue
        mentions = any(n in text for n in needles)
        out.append(check(name, mentions, f"~/{found} present; mentions gateway: {'yes' if mentions else 'no'}"))
    return out


# ---------------------------------------------------------------- driver

def run_checks(root: Path, fleet_path: Path, home: Path, wing_override: str | None, gateway_timeout: float) -> tuple[list[dict], str, str]:
    fleet: dict | None = None
    fleet_err = None
    if fleet_path.exists():
        data, fleet_err = load_yaml(fleet_path)
        fleet = data if isinstance(data, dict) else None
    hostname = detect_hostname()
    wing, source = resolve_wing(fleet, wing_override, hostname)

    checks: list[dict] = []
    wing_check = check_wing(fleet, wing, source, hostname)
    if fleet is None and fleet_err:
        wing_check["detail"] = f"{fleet_path.name} does not parse: {fleet_err}"
    checks.append(wing_check)
    profile_check, node = check_node_profile(root, wing)
    checks.append(profile_check)
    checks.append(check_tailscale())
    checks.append(check_gateway(fleet, gateway_timeout))
    checks.append(check_fleet_boundary(fleet))
    checks.append(check_remote_management())
    checks.append(check_ssh())
    checks.append(check_hermes(fleet, wing))
    checks.append(check_tenants(root))
    checks.extend(check_runtimes(home, fleet, node))
    return checks, wing, hostname


def render(checks: list[dict], wing: str, hostname: str) -> str:
    lines = [f"== Snow Gloves fleet doctor ==  wing={wing or 'unknown'}  host='{hostname}'"]
    for c in checks:
        tag = "OK  " if c["ok"] else ("FAIL" if c["critical"] else "WARN")
        lines.append(f"  {tag} {c['name']:<18} {c['detail']}")
    failed = [c["name"] for c in checks if c["critical"] and not c["ok"]]
    warned = sum(1 for c in checks if not c["critical"] and not c["ok"])
    if failed:
        lines.append(f"FAIL: {', '.join(failed)} ({warned} warnings)")
    else:
        lines.append(f"OK: critical checks pass ({warned} warnings)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Snow Gloves fleet doctor (read-only).")
    ap.add_argument("--root", type=Path, default=None,
                    help="checkout holding fleet.yaml, nodes/ and tenants/ (default: $SNOWGLOVES_DATA, else this checkout)")
    ap.add_argument("--fleet", type=Path, default=None, help="fleet inventory (default: <root>/fleet.yaml)")
    ap.add_argument("--home", type=Path, default=Path.home(), help="home dir to look for runtime configs")
    ap.add_argument("--wing", default=None, help="override wing identity (else SNOWGLOVES_NODE, else hostname)")
    ap.add_argument("--gateway-timeout", type=float, default=3.0, help="seconds per /healthz probe")
    ap.add_argument("--json", action="store_true", help="print the check list as JSON")
    args = ap.parse_args(argv)

    root = (args.root or paths.data_root()).resolve()
    fleet_path = (args.fleet or root / "fleet.yaml").resolve()
    checks, wing, hostname = run_checks(root, fleet_path, args.home.expanduser(), args.wing, args.gateway_timeout)
    if args.json:
        print(json.dumps(checks, indent=2))
    else:
        print(render(checks, wing, hostname))
    return 0 if all(c["ok"] for c in checks if c["critical"]) else 1


if __name__ == "__main__":
    sys.exit(main())

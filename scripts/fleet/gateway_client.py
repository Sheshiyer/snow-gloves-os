#!/usr/bin/env python3
"""Point this machine's CLI surfaces at the Snow Gloves fleet gateway.

Surfaces (paths are relative to --home, default $HOME):
  claude    .claude/settings.json          env.ANTHROPIC_BASE_URL (root, no /v1) + ANTHROPIC_AUTH_TOKEN
  codex     .codex/config.toml             [model_providers.omniroute] base_url .../v1, env_key
  grok      .grok/config.toml              [model.te-*] blocks, base_url .../v1, env_key
  opencode  .config/opencode/opencode.json provider.omniroute.options.baseURL .../v1, apiKey {env:VAR}

Commands:
  set-url   dry-run by default (unified diff per file); --apply writes with a timestamped .bak
  status    current base URL per surface, FLEET or NOT-FLEET, and a GET /healthz probe
  doctor    status + tailscale presence + key_ref resolution (FOUND/MISSING, value never printed)

Key handling: TOML and OpenCode surfaces receive a reference (an env var name). Claude's
settings.json needs a literal ANTHROPIC_AUTH_TOKEN, so at --apply time the value is read from
--key-ref (env:VAR or keychain:SERVICE) and written to the file; stdout only ever shows [redacted].

Python 3.10+, stdlib plus pyyaml (only to read fleet.yaml for the default gateway host).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - 3.10 fallback uses regex detection
    tomllib = None

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FLEET = REPO_ROOT / "fleet.yaml"
SURFACES = ("claude", "codex", "grok", "opencode")
SURFACE_PATHS = {
    "claude": ".claude/settings.json",
    "codex": ".codex/config.toml",
    "grok": ".grok/config.toml",
    "opencode": ".config/opencode/opencode.json",
}
BLOCK_BEGIN = "# >>> snowgloves fleet gateway (managed by scripts/fleet/gateway_client.py) >>>"
BLOCK_END = "# <<< snowgloves fleet gateway <<<"
GROK_COMBOS = ("orchestrator", "build", "fast", "plan")
GROK_MARKER_TABLE = "model.te-orchestrator"
REDACTED = "[redacted]"
SENTINEL = "__SNOWGLOVES_SECRET_SENTINEL__"
DEFAULT_ENV_VAR = "OMNIROUTE_API_KEY"
SECRET_NAME_RE = re.compile(r"key|token|secret|password", re.I)
SECRET_NAME_ALLOW = ("env_key", "key_ref", "allowed", "scope")


# ----------------------------------------------------------------------------- helpers

def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def load_json(path: Path) -> dict:
    text = read_text(path)
    if text is None or not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: top-level JSON must be an object")
    return data


def dump_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def fleet_gateway(fleet_path: Path) -> tuple[str | None, int | None]:
    """Return (host, port) from fleet.yaml gateway.url, or (None, None)."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(fleet_path.read_text(encoding="utf-8")) or {}
        url = str(data["gateway"]["url"])
    except Exception:
        return None, None
    return split_host_port(url)


def split_host_port(url: str | None) -> tuple[str | None, int | None]:
    if not url:
        return None, None
    m = re.match(r"^\s*(?:https?://)?([^:/\s]+)(?::(\d+))?", url)
    if not m:
        return None, None
    return m.group(1), int(m.group(2) or 80)


def parse_key_ref(ref: str) -> tuple[str, str]:
    kind, _, name = ref.partition(":")
    if kind not in ("env", "keychain") or not name:
        raise SystemExit(f"bad --key-ref {ref!r}: use env:VAR or keychain:SERVICE")
    return kind, name


def env_var_for(kind: str, name: str) -> str:
    """The env var name written into TOML/OpenCode surfaces."""
    return name if kind == "env" else DEFAULT_ENV_VAR


def resolve_key(kind: str, name: str) -> str | None:
    """Return the secret value or None. Never log it."""
    if kind == "env":
        return os.environ.get(name) or None
    security = shutil.which("security")
    if not security:
        return None
    try:
        proc = subprocess.run(
            [security, "find-generic-password", "-s", name, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def redact_text(text: str) -> str:
    """Hide secret-looking values before anything reaches stdout."""

    def _json_sub(m: re.Match) -> str:
        key, value = m.group(1), m.group(3)
        if any(a in key.lower() for a in SECRET_NAME_ALLOW) or value.startswith(("{env:", "${")):
            return m.group(0)
        return f'{m.group(1)}"{REDACTED}"'

    def _toml_sub(m: re.Match) -> str:
        key = m.group(2)
        if any(a in key.lower() for a in SECRET_NAME_ALLOW):
            return m.group(0)
        return f'{m.group(1)}"{REDACTED}"'

    text = text.replace(SENTINEL, REDACTED)
    text = re.sub(r'("([^"\n]*)"\s*:\s*)"([^"\n]*)"',
                  lambda m: _json_sub(m) if SECRET_NAME_RE.search(m.group(2)) else m.group(0), text)
    text = re.sub(r'(?im)^(\s*([\w.\-]*(?:key|token|secret|password)[\w.\-]*)\s*=\s*)"[^"\n]*"', _toml_sub, text)
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", REDACTED, text)
    text = re.sub(r"Bearer [A-Za-z0-9._\-]{16,}", f"Bearer {REDACTED}", text)
    return text


# ----------------------------------------------------------------------------- TOML inspection

def toml_parse(text: str) -> dict | None:
    if tomllib is None:
        return None
    try:
        return tomllib.loads(text)
    except Exception:
        return None


def toml_table_present(text: str, dotted: str) -> bool:
    data = toml_parse(text)
    if data is not None:
        cur: object = data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return False
            cur = cur[part]
        return isinstance(cur, dict)
    pat = r"(?m)^[ \t]*\[" + re.escape(dotted) + r"\][ \t]*$"
    return re.search(pat, text) is not None


def toml_table_value(text: str, dotted: str, key: str) -> str | None:
    data = toml_parse(text)
    if data is not None:
        cur: object = data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        if isinstance(cur, dict) and isinstance(cur.get(key), str):
            return cur[key]
        return None
    header = re.compile(r"(?m)^[ \t]*\[" + re.escape(dotted) + r"\][ \t]*$")
    m = header.search(text)
    if not m:
        return None
    body = text[m.end():]
    nxt = re.search(r"(?m)^[ \t]*\[", body)
    body = body[: nxt.start()] if nxt else body
    v = re.search(r"(?m)^\s*" + re.escape(key) + r"\s*=\s*\"([^\"]*)\"", body)
    return v.group(1) if v else None


def toml_toplevel_present(text: str, key: str) -> bool:
    data = toml_parse(text)
    if data is not None:
        return key in data and not isinstance(data[key], dict)
    head = re.split(r"(?m)^[ \t]*\[", text, maxsplit=1)[0]
    return re.search(r"(?m)^[ \t]*" + re.escape(key) + r"[ \t]*=", head) is not None


def toml_insert_toplevel(text: str, line: str) -> str:
    """Insert a top-level key before the first table header (top-level keys may not follow a table)."""
    m = re.search(r"(?m)^[ \t]*\[", text)
    if not m:
        base = text if text.endswith("\n") or not text else text + "\n"
        return base + line + "\n"
    head = text[: m.start()].rstrip("\n")
    head = head + "\n" if head else ""
    return head + line + "\n\n" + text[m.start():]


def ensure_nl(text: str) -> str:
    return text if not text or text.endswith("\n") else text + "\n"


# ----------------------------------------------------------------------------- plans

@dataclass
class Plan:
    surface: str
    path: Path
    old_text: str | None
    new_text: str
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (self.old_text or "") != self.new_text


def plan_claude(path: Path, root_url: str) -> Plan:
    old = read_text(path)
    data = load_json(path)
    env = data.get("env")
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    notes = []
    if "ANTHROPIC_API_KEY" in env:
        notes.append("env.ANTHROPIC_API_KEY is also set; Claude Code may prefer it over ANTHROPIC_AUTH_TOKEN")
    env["ANTHROPIC_BASE_URL"] = root_url
    env["ANTHROPIC_AUTH_TOKEN"] = SENTINEL
    return Plan("claude", path, old, dump_json(data), notes)


def plan_codex(path: Path, v1_url: str, env_var: str) -> Plan:
    old = read_text(path)
    text = old or ""
    notes = []
    if toml_table_present(text, "model_providers.omniroute"):
        current = toml_table_value(text, "model_providers.omniroute", "base_url")
        notes.append("present" if current == v1_url else f"present (base_url is {current}; not rewritten, edit by hand)")
        new = text
    else:
        block = (
            f"\n{BLOCK_BEGIN}\n"
            "[model_providers.omniroute]\n"
            'name = "OmniRoute"\n'
            f'base_url = "{v1_url}"\n'
            'wire_api = "responses"\n'
            f'env_key = "{env_var}"\n'
            f"{BLOCK_END}\n"
        )
        new = ensure_nl(text) + block
    if toml_toplevel_present(text, "model_provider"):
        notes.append("model_provider already set at top level (left unchanged)")
    else:
        new = toml_insert_toplevel(new, 'model_provider = "omniroute"  # snowgloves fleet gateway default')
    return Plan("codex", path, old, new, notes)


def plan_grok(path: Path, v1_url: str, env_var: str) -> Plan:
    old = read_text(path)
    text = old or ""
    notes = []
    if toml_table_present(text, GROK_MARKER_TABLE):
        current = toml_table_value(text, GROK_MARKER_TABLE, "base_url")
        notes.append("present" if current == v1_url else f"present (base_url is {current}; not rewritten, edit by hand)")
        return Plan("grok", path, old, text, notes)
    tables = []
    for combo in GROK_COMBOS:
        tables.append(
            f"[model.te-{combo}]\n"
            f'model = "noesis-{combo}"\n'
            f'base_url = "{v1_url}"\n'
            f'name = "Fleet noesis-{combo}"\n'
            f'env_key = ["{env_var}"]\n'
            'api_backend = "chat_completions"\n'
            "context_window = 200000\n"
        )
    block = f"\n{BLOCK_BEGIN}\n" + "\n".join(tables) + f"{BLOCK_END}\n"
    return Plan("grok", path, old, ensure_nl(text) + block, notes)


def plan_opencode(path: Path, v1_url: str, env_var: str) -> Plan:
    old = read_text(path)
    data = load_json(path)
    notes = []
    providers = data.get("provider")
    if not isinstance(providers, dict):
        providers = {}
        data["provider"] = providers
    om = providers.get("omniroute")
    if not isinstance(om, dict):
        om = {}
        providers["omniroute"] = om
    om.setdefault("name", "OmniRoute")
    om.setdefault("npm", "@ai-sdk/openai-compatible")
    options = om.get("options")
    if not isinstance(options, dict):
        options = {}
        om["options"] = options
    options["baseURL"] = v1_url
    api_key = options.get("apiKey")
    ref = "{env:" + env_var + "}"
    if not api_key or (isinstance(api_key, str) and api_key.startswith("{env:")):
        options["apiKey"] = ref
    else:
        notes.append("provider.omniroute.options.apiKey holds a literal; left in place (replace with " + ref + " by hand)")
    enabled = data.get("enabled_providers")
    if isinstance(enabled, list) and "omniroute" not in enabled:
        enabled.append("omniroute")
        notes.append("added omniroute to enabled_providers")
    return Plan("opencode", path, old, dump_json(data), notes)


def build_plans(home: Path, surfaces: list[str], host: str, port: int, env_var: str) -> list[Plan]:
    root_url = f"http://{host}:{port}"
    v1_url = root_url + "/v1"
    plans = []
    for s in surfaces:
        path = home / SURFACE_PATHS[s]
        if s == "claude":
            plans.append(plan_claude(path, root_url))
        elif s == "codex":
            plans.append(plan_codex(path, v1_url, env_var))
        elif s == "grok":
            plans.append(plan_grok(path, v1_url, env_var))
        elif s == "opencode":
            plans.append(plan_opencode(path, v1_url, env_var))
    return plans


def print_diff(plan: Plan) -> None:
    old = redact_text(plan.old_text or "").splitlines(keepends=True)
    new = redact_text(plan.new_text).splitlines(keepends=True)
    src = str(plan.path) if plan.old_text is not None else "/dev/null"
    for line in difflib.unified_diff(old, new, fromfile=src, tofile=f"{plan.path} (proposed)"):
        sys.stdout.write(line if line.endswith("\n") else line + "\n")


def write_plan(plan: Plan, secret: str | None) -> str:
    content = plan.new_text
    if SENTINEL in content:
        if not secret:
            return "skipped (key_ref did not resolve; literal token required)"
        content = content.replace(SENTINEL, secret)
    if (plan.old_text or "") == content:
        return "unchanged"
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    backup = ""
    if plan.old_text is not None:
        bak = plan.path.with_name(plan.path.name + f".bak.{utc_stamp()}")
        shutil.copy2(plan.path, bak)
        backup = f", backup {bak.name}"
    plan.path.write_text(content, encoding="utf-8")
    try:
        os.chmod(plan.path, 0o600)
    except OSError:
        pass
    return f"written{backup}"


# ----------------------------------------------------------------------------- status

def surface_base_url(surface: str, path: Path) -> str | None:
    text = read_text(path)
    if text is None:
        return None
    try:
        if surface == "claude":
            env = load_json(path).get("env", {})
            return env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
        if surface == "codex":
            return toml_table_value(text, "model_providers.omniroute", "base_url")
        if surface == "grok":
            return toml_table_value(text, GROK_MARKER_TABLE, "base_url")
        if surface == "opencode":
            return (((load_json(path).get("provider") or {}).get("omniroute") or {}).get("options") or {}).get("baseURL")
    except Exception as exc:  # unreadable file is a status, not a crash
        return f"(unreadable: {type(exc).__name__})"
    return None


def is_fleet(base_url: str | None, host: str, port: int) -> bool:
    h, p = split_host_port(base_url)
    return bool(h) and h.lower() == host.lower() and p == port


def probe_health(host: str, port: int, timeout: float = 3.0) -> tuple[str, str]:
    url = f"http://{host}:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - fixed scheme/path
            return url, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return url, f"HTTP {exc.code}"
    except Exception as exc:
        return url, f"unreachable ({type(exc).__name__})"


def run_status(home: Path, surfaces: list[str], host: str, port: int, probe: bool) -> int:
    print(f"gateway: http://{host}:{port}")
    all_fleet = True
    for s in surfaces:
        path = home / SURFACE_PATHS[s]
        base = surface_base_url(s, path)
        fleet = is_fleet(base, host, port)
        all_fleet = all_fleet and fleet
        shown = base if base else "(missing)"
        print(f"  {s:<9} {'FLEET' if fleet else 'NOT-FLEET':<9} base={shown}  file={path}")
    if probe:
        url, result = probe_health(host, port)
        print(f"probe: GET {url} -> {result}")
    return 0 if all_fleet else 1


def run_doctor(home: Path, surfaces: list[str], host: str, port: int, probe: bool, key_ref: str | None) -> int:
    rc = run_status(home, surfaces, host, port, probe)
    ok = rc == 0
    ts = shutil.which("tailscale") or (
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        if Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale").exists() else None
    )
    print(f"tailscale: {'present (' + ts + ')' if ts else 'MISSING (install Tailscale; the gateway is reachable only over the tailnet)'}")
    ok = ok and bool(ts)
    env_var = DEFAULT_ENV_VAR
    if key_ref:
        kind, name = parse_key_ref(key_ref)
        env_var = env_var_for(kind, name)
        if kind == "env":
            found = bool(os.environ.get(name))
            print(f"key_ref env:{name}: {'set' if found else 'unset'}")
        else:
            if not shutil.which("security"):
                found = False
                print(f"key_ref keychain:{name}: cannot check (no `security` tool; not macOS)")
            else:
                found = resolve_key(kind, name) is not None
                print(f"key_ref keychain:{name}: {'FOUND' if found else 'MISSING'}")
                print(f'  shell hint: export {env_var}="$(security find-generic-password -s {name} -w)"')
        ok = ok and found
    exported = bool(os.environ.get(env_var))
    print(f"env {env_var}: {'set' if exported else 'unset'} (codex, grok and opencode read the key from this variable)")
    ok = ok and exported
    print(f"doctor: {'OK' if ok else 'ATTENTION'}")
    return 0 if ok else 1


# ----------------------------------------------------------------------------- set-url

def run_set_url(home: Path, surfaces: list[str], host: str, port: int, key_ref: str, apply: bool) -> int:
    kind, name = parse_key_ref(key_ref)
    env_var = env_var_for(kind, name)
    print(f"mode: {'APPLY' if apply else 'dry-run (pass --apply to write)'}")
    print(f"gateway: http://{host}:{port}  key_ref: {key_ref}  env var written to TOML/JSON references: {env_var}")
    if kind == "keychain":
        print(f'shell profile line (no secret shown): export {env_var}="$(security find-generic-password -s {name} -w)"')
    plans = build_plans(home, surfaces, host, port, env_var)
    secret = resolve_key(kind, name) if apply else None
    rc = 0
    for plan in plans:
        print(f"--- {plan.surface}: {plan.path}")
        for note in plan.notes:
            print(f"    note: {note}")
        if not plan.changed:
            print("    no change")
            continue
        print_diff(plan)
        if apply:
            result = write_plan(plan, secret)
            print(f"    {result}")
            if result.startswith("skipped"):
                rc = 1
    if apply and secret is None and any(SENTINEL in p.new_text for p in plans):
        print(f"warning: {key_ref} did not resolve; the claude surface was not written", file=sys.stderr)
    return rc


# ----------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", type=Path, default=Path(os.environ.get("HOME", str(Path.home()))),
                        help="redirect all surface paths (tests)")
    common.add_argument("--fleet", type=Path, default=DEFAULT_FLEET, help="fleet.yaml for the default gateway host")
    common.add_argument("--host", help="gateway overlay name or IP (default: fleet.yaml gateway.url)")
    common.add_argument("--port", type=int, help="gateway port (default: fleet.yaml, else 20128)")
    common.add_argument("--surfaces", default=",".join(SURFACES), help="comma list of claude,codex,grok,opencode")
    common.add_argument("--no-probe", action="store_true", help="skip the /healthz probe")

    ap = argparse.ArgumentParser(prog="gateway_client.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set-url", parents=[common], help="write gateway URL + key reference into client surfaces")
    s.add_argument("--key-ref", required=True, help="env:VAR or keychain:SERVICE")
    s.add_argument("--apply", action="store_true", help="write files (default is dry-run)")
    sub.add_parser("status", parents=[common], help="show each surface's base URL and probe /healthz")
    d = sub.add_parser("doctor", parents=[common], help="status + tailscale + key_ref checks")
    d.add_argument("--key-ref", help="env:VAR or keychain:SERVICE")
    return ap


def resolve_target(args: argparse.Namespace) -> tuple[str, int]:
    f_host, f_port = fleet_gateway(args.fleet)
    host = args.host or f_host
    port = args.port or f_port or 20128
    if not host:
        raise SystemExit("no --host given and fleet.yaml gateway.url not readable")
    return host, port


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    unknown = [s for s in surfaces if s not in SURFACES]
    if unknown:
        raise SystemExit(f"unknown surfaces: {', '.join(unknown)} (choose from {', '.join(SURFACES)})")
    host, port = resolve_target(args)
    home = args.home.expanduser()
    if args.cmd == "set-url":
        return run_set_url(home, surfaces, host, port, args.key_ref, args.apply)
    if args.cmd == "status":
        return run_status(home, surfaces, host, port, not args.no_probe)
    if args.cmd == "doctor":
        return run_doctor(home, surfaces, host, port, not args.no_probe, args.key_ref)
    return 2


if __name__ == "__main__":
    sys.exit(main())

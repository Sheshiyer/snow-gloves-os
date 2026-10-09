#!/usr/bin/env python3
"""Wire OmniRoute into Claude Code and Codex as an opt-in, never as the global provider.

    python3 scripts/wire_omniroute.py --status
    python3 scripts/wire_omniroute.py                      # dry run: show what --apply would change
    python3 scripts/wire_omniroute.py --apply              # strip global overrides, add opt-in layers
    python3 scripts/wire_omniroute.py --store-key          # read the combos key from stdin into Keychain
    python3 scripts/wire_omniroute.py --refresh            # rebuild the Codex combo catalog only
    python3 scripts/wire_omniroute.py --project PATH       # route one project through OmniRoute
    python3 scripts/wire_omniroute.py --project PATH --remove
    python3 scripts/wire_omniroute.py --rollback

Native stays the default. Opt in per session with `claude-or` / `codex-or`, or per project with
--project. The gateway key lives only in macOS Keychain and is fetched at request time; this script
never writes it to a file and never prints it. Every edit is preceded by a `.wire-bak.<ts>` copy.
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
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:20128"
KEYCHAIN_SERVICE = "OmniRoute Combos Key"
SECURITY_BIN = "/usr/bin/security"
DEFAULT_MODEL = "noesis-orchestrator"
PROVIDER_ID = "omniroute"
PROFILE_ID = "omniroute"
CONTEXT_WINDOW = 200_000  # floor across live combos, see router/omniroute-codex.sh
COMPACT_LIMIT = 170_000
CLAUDE_COMPACT_WINDOW = "190000"
COMBO_PREFIXES = ("noesis-", "temperance-")
CLAUDE_OVERRIDE_ENV = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
)
CATALOG_MODULE = Path.home() / ".temperance_engine/router/codex-routed-model-catalog.ts"


# --------------------------------------------------------------------------- Claude


def _is_gateway_url(url: object) -> bool:
    return isinstance(url, str) and bool(re.search(r":20128(/|$)", url))


def strip_claude_global(text: str) -> str:
    """Remove the global OmniRoute override from ~/.claude/settings.json; keep everything else."""
    data = json.loads(text) if text.strip() else {}
    env = data.get("env")
    if isinstance(env, dict) and _is_gateway_url(env.get("ANTHROPIC_BASE_URL")):
        for key in CLAUDE_OVERRIDE_ENV:
            env.pop(key, None)
        if not env:
            data.pop("env")
    model = data.get("model")
    if isinstance(model, str) and model.startswith(COMBO_PREFIXES):
        data.pop("model")
    return json.dumps(data, indent=2) + "\n"


def key_helper_command(user: str) -> str:
    return f'{SECURITY_BIN} find-generic-password -a "{user}" -s "{KEYCHAIN_SERVICE}" -w'


def claude_layer(base_url: str, user: str) -> dict:
    """Settings layered on top of the native config by `claude --settings`; no key on disk."""
    return {
        "$schema": "https://json.schemastore.org/claude-code-settings.json",
        "model": DEFAULT_MODEL,
        "apiKeyHelper": key_helper_command(user),
        "env": {
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_MODEL": DEFAULT_MODEL,
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
            "CLAUDE_CODE_AUTO_COMPACT_WINDOW": CLAUDE_COMPACT_WINDOW,
        },
    }


def merge_project_claude(existing: str, layer: dict) -> str:
    data = json.loads(existing) if existing.strip() else {}
    env = data.setdefault("env", {})
    env.update(layer["env"])
    data["apiKeyHelper"] = layer["apiKeyHelper"]
    data["model"] = layer["model"]
    return json.dumps(data, indent=2) + "\n"


def unmerge_project_claude(existing: str) -> str | None:
    """Remove the OmniRoute keys; return None when nothing else is left (caller deletes the file)."""
    data = json.loads(existing) if existing.strip() else {}
    env = data.get("env", {})
    if isinstance(env, dict):
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "CLAUDE_CODE_AUTO_COMPACT_WINDOW"):
            env.pop(key, None)
        if not env:
            data.pop("env", None)
    if isinstance(data.get("apiKeyHelper"), str) and KEYCHAIN_SERVICE in data["apiKeyHelper"]:
        data.pop("apiKeyHelper")
    if data.get("model") == DEFAULT_MODEL:
        data.pop("model")
    data.pop("$schema", None)
    return json.dumps(data, indent=2) + "\n" if data else None


# --------------------------------------------------------------------------- Codex TOML

_HEADER = re.compile(r"^\s*\[\[?\s*(.+?)\s*\]\]?\s*(#.*)?$")
_BARE_KEY_PATH = re.compile(r"^[A-Za-z0-9_.\- ]*$")


def _table_name(line: str) -> str | None:
    """Return the table name when `line` is a [table] header, else None (array rows, values)."""
    match = _HEADER.match(line)
    if not match:
        return None
    name = match.group(1).strip()
    # Quoted key segments may hold any character; everything outside quotes must be a bare key path.
    if not _BARE_KEY_PATH.match(re.sub(r'"[^"]*"|\'[^\']*\'', "", name)):
        return None
    return name


def split_blocks(text: str) -> list[tuple[str | None, list[str]]]:
    """Split TOML text into (table-name, lines) blocks; the first block is the top-level preamble."""
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        name = _table_name(line)
        if name is not None:
            blocks.append((name, [line]))
        else:
            blocks[-1][1].append(line)
    return blocks


def join_blocks(blocks: list[tuple[str | None, list[str]]]) -> str:
    out: list[str] = []
    for _name, lines in blocks:
        while lines and not lines[-1].strip():
            lines = lines[:-1]
        if not lines:
            continue
        if out:
            out.append("")
        out.extend(lines)
    return "\n".join(out) + "\n"


def provider_block(base_url: str, user: str) -> list[tuple[str | None, list[str]]]:
    args = json.dumps(["find-generic-password", "-a", user, "-s", KEYCHAIN_SERVICE, "-w"])
    return [
        (f"model_providers.{PROVIDER_ID}", [
            f"[model_providers.{PROVIDER_ID}]",
            'name = "OmniRoute"',
            f'base_url = "{base_url.rstrip("/")}/v1"',
            'wire_api = "responses"',
            "requires_openai_auth = false",
        ]),
        (f"model_providers.{PROVIDER_ID}.auth", [
            f"[model_providers.{PROVIDER_ID}.auth]",
            f'command = "{SECURITY_BIN}"',
            f"args = {args}",
            "timeout_ms = 5000",
            "refresh_interval_ms = 300000",
        ]),
    ]


def codex_profile_file(base_url: str, catalog_path: str, user: str) -> str:
    """~/.codex/omniroute.config.toml: Codex 0.160 'profile v2' layer, selected with `codex --profile omniroute`."""
    lines = [
        "# Managed by scripts/wire_omniroute.py. Opt-in only: select with `codex --profile omniroute` (or codex-or).",
        f'model_provider = "{PROVIDER_ID}"',
        f'model = "{DEFAULT_MODEL}"',
        f'model_catalog_json = "{catalog_path}"',
        f"model_context_window = {CONTEXT_WINDOW}",
        f"model_auto_compact_token_limit = {COMPACT_LIMIT}",
        "",
    ]
    for _name, block in provider_block(base_url, user):
        lines += block + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def edit_codex(text: str) -> str:
    """Strip the global OmniRoute override from ~/.codex/config.toml; every other table is left byte-for-byte."""
    blocks = split_blocks(text)
    pre_name, pre_lines = blocks[0]
    pre_lines = [l for l in pre_lines if not re.match(rf'^\s*model_provider\s*=\s*"{PROVIDER_ID}"\s*(#.*)?$', l)]
    blocks[0] = (pre_name, pre_lines)
    # the shell-env block that injected ANTHROPIC_* into every command Codex runs
    blocks = [b for b in blocks if b[0] != "shell_environment_policy.set" or "20128" not in "\n".join(b[1])]
    # legacy omniroute tables; the profile file now owns them (legacy [profiles.*] also breaks --profile)
    ours = {f"model_providers.{PROVIDER_ID}", f"model_providers.{PROVIDER_ID}.auth", f"profiles.{PROFILE_ID}"}
    blocks = [b for b in blocks if b[0] not in ours]
    return join_blocks(blocks)


# --------------------------------------------------------------------------- catalog


SLUG = re.compile(r"^[A-Za-z0-9_~./:+-]{1,300}$")  # what the host's routedModelCatalog() accepts


def combo_entries(models_payload: dict, include_auto: bool = False) -> list[dict]:
    """Your configured combos. OmniRoute's built-in auto/* virtual combos are opt-in; ids Codex can't use as a slug are skipped."""
    rows = [
        m for m in models_payload.get("data", [])
        if m.get("owned_by") == "combo"
        and SLUG.match(m.get("id", ""))
        and (include_auto or not m["id"].startswith("auto/"))
    ]
    return sorted(rows, key=lambda m: m["id"])


def routed_template(rows: list[dict], module: Path = CATALOG_MODULE) -> list[dict]:
    """Run the host's routedModelCatalog() once per combo so the tool-harness metadata is reused."""
    bun = shutil.which("bun") or "/opt/homebrew/bin/bun"
    script = (
        f'import {{ routedModelCatalog }} from "{module}";'
        "const rows = JSON.parse(await Bun.stdin.text());"
        "console.log(JSON.stringify(rows.map(r => routedModelCatalog(r.id, r.ctx).models[0])));"
    )
    payload = json.dumps([{"id": r["id"], "ctx": int(r.get("context_length") or CONTEXT_WINDOW)} for r in rows])
    out = subprocess.run([bun, "-e", script], input=payload, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"catalog template unavailable: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def build_catalog(rows: list[dict], template: list[dict]) -> dict:
    models = []
    for index, (row, entry) in enumerate(zip(rows, template)):
        entry = dict(entry)
        entry.update(
            slug=row["id"],
            display_name=row["id"],
            description=(row.get("description") or "OmniRoute combo").split(" · synced")[0][:300],
            visibility="list",
            priority=index,
        )
        models.append(entry)
    return {"models": models}


# --------------------------------------------------------------------------- IO helpers


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def write_with_backup(path: Path, new: str, dry: bool, notes: list[str]) -> None:
    old = read(path)
    if old == new:
        notes.append(f"unchanged  {path}")
        return
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"{path} (current)", f"{path} (new)", n=1))
    notes.append(f"{'would change' if dry else 'changed'}  {path}")
    if dry:
        notes.append(redact(diff))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.wire-bak.{stamp()}"))
    path.write_text(new)
    path.chmod(mode)


def redact(text: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-<redacted>", text)


def keychain_get(user: str) -> str | None:
    out = subprocess.run([SECURITY_BIN, "find-generic-password", "-a", user, "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    return out.stdout.strip() or None if out.returncode == 0 else None


def keychain_set(user: str, key: str) -> None:
    subprocess.run([SECURITY_BIN, "add-generic-password", "-U", "-a", user, "-s", KEYCHAIN_SERVICE, "-w", key], check=True, capture_output=True)


def fetch_models(base_url: str, key: str) -> dict:
    req = urllib.request.Request(f"{base_url.rstrip('/')}/v1/models", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def launcher_scripts(settings_layer: Path) -> dict[str, str]:
    return {
        "claude-or": (
            "#!/usr/bin/env bash\n"
            "# Claude Code through OmniRoute for this session only; native config stays layered underneath.\n"
            "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL\n"
            f'exec claude --settings "{settings_layer}" "$@"\n'
        ),
        "codex-or": (
            "#!/usr/bin/env bash\n"
            "# Codex through OmniRoute for this session only; /model lists the combo catalog.\n"
            f'exec codex --profile {PROFILE_ID} "$@"\n'
        ),
    }


# --------------------------------------------------------------------------- commands


def paths(home: Path) -> dict[str, Path]:
    return {
        "claude_settings": home / ".claude/settings.json",
        "claude_layer": home / ".claude/omniroute.settings.json",
        "codex_config": home / ".codex/config.toml",
        "codex_profile": home / f".codex/{PROFILE_ID}.config.toml",
        "codex_catalog": home / ".codex/omniroute-models.json",
    }


def cmd_apply(args, user: str) -> int:
    p = paths(Path(args.home))
    notes: list[str] = []
    dry = not args.apply
    key = os.environ.get("OMNIROUTE_API_KEY") or keychain_get(user)
    catalog_text = read(p["codex_catalog"])
    if key:
        rows = combo_entries(fetch_models(args.base_url, key), args.include_auto)
        if not rows:
            print("gateway returned no combos; refusing to write an empty catalog", file=sys.stderr)
            return 1
        catalog_text = json.dumps(build_catalog(rows, routed_template(rows)), indent=2) + "\n"
        notes.append(f"combos     {len(rows)} found")
    else:
        notes.append("combos     skipped (no key in Keychain yet; run --store-key, then --refresh)")
    write_with_backup(p["claude_settings"], strip_claude_global(read(p["claude_settings"])), dry, notes)
    write_with_backup(p["claude_layer"], json.dumps(claude_layer(args.base_url, user), indent=2) + "\n", dry, notes)
    write_with_backup(p["codex_config"], edit_codex(read(p["codex_config"])), dry, notes)
    write_with_backup(p["codex_profile"], codex_profile_file(args.base_url, str(p["codex_catalog"]), user), dry, notes)
    if catalog_text:
        write_with_backup(p["codex_catalog"], catalog_text, dry, notes)
    for name, body in launcher_scripts(p["claude_layer"]).items():
        target = Path(args.bin_dir) / name
        if read(target) != body:
            notes.append(f"{'would write' if dry else 'wrote'}  {target}")
            if not dry:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body)
                target.chmod(0o755)
    print("\n".join(notes))
    if dry:
        print("\n(dry run; pass --apply to write)")
    return 0


def cmd_refresh(args, user: str) -> int:
    p = paths(Path(args.home))
    key = os.environ.get("OMNIROUTE_API_KEY") or keychain_get(user)
    if not key:
        print("no key in Keychain; run --store-key first", file=sys.stderr)
        return 1
    rows = combo_entries(fetch_models(args.base_url, key), args.include_auto)
    if not rows:
        print("gateway returned no combos; catalog left as is", file=sys.stderr)
        return 1
    notes: list[str] = []
    write_with_backup(p["codex_catalog"], json.dumps(build_catalog(rows, routed_template(rows)), indent=2) + "\n", False, notes)
    print("\n".join(notes), f"\n{len(rows)} combos")
    return 0


def cmd_store_key(user: str) -> int:
    key = sys.stdin.readline().strip()
    if not key or re.search(r"\s", key):
        print("expected one key on stdin", file=sys.stderr)
        return 2
    keychain_set(user, key)
    print(f"stored in Keychain service '{KEYCHAIN_SERVICE}'")
    return 0


def cmd_project(args, user: str) -> int:
    root = Path(args.project).expanduser().resolve()
    notes: list[str] = []
    claude_local = root / ".claude/settings.local.json"
    if args.remove:
        slim = unmerge_project_claude(read(claude_local)) if claude_local.exists() else None
        if claude_local.exists():
            if slim is None:
                claude_local.unlink()
                notes.append(f"removed  {claude_local}")
            else:
                write_with_backup(claude_local, slim, False, notes)
    else:
        write_with_backup(claude_local, merge_project_claude(read(claude_local), claude_layer(args.base_url, user)), False, notes)
        notes.append("note: keep .claude/settings.local.json out of git (Claude Code ignores it by default)")
        notes.append("note: Codex has no per-project profile selector in 0.160; use codex-or from that folder")
    print("\n".join(notes))
    return 0


def cmd_rollback(args) -> int:
    p = paths(Path(args.home))
    restored = 0
    for name in ("claude_settings", "codex_config"):
        target = p[name]
        backups = sorted(target.parent.glob(f"{target.name}.wire-bak.*"))
        if not backups:
            print(f"no wire backup for {target}")
            continue
        shutil.copy2(backups[0], target)  # oldest = the untouched original
        print(f"restored {target} from {backups[0].name}")
        restored += 1
    for name in ("claude_layer", "codex_catalog", "codex_profile"):
        if p[name].exists():
            p[name].unlink()
            print(f"removed {p[name]}")
    for name in launcher_scripts(p["claude_layer"]):
        (Path(args.bin_dir) / name).unlink(missing_ok=True)
    return 0 if restored else 1


def cmd_status(args, user: str) -> int:
    p = paths(Path(args.home))
    claude = read(p["claude_settings"])
    codex = read(p["codex_config"])
    key = keychain_get(user)
    checks = [
        ("claude global override removed", "ANTHROPIC_BASE_URL" not in claude and '"noesis-' not in claude),
        ("codex global provider removed", not re.search(rf'^model_provider\s*=\s*"{PROVIDER_ID}"', codex, re.M)),
        ("codex shell env clean", "ANTHROPIC_AUTH_TOKEN" not in codex),
        ("codex omniroute profile file", p["codex_profile"].exists()),
        ("codex has no legacy omniroute tables", "[profiles.omniroute]" not in codex and "[model_providers.omniroute" not in codex),
        ("claude layer file", p["claude_layer"].exists()),
        ("codex combo catalog", p["codex_catalog"].exists()),
        ("key in Keychain", key is not None),
        ("no gateway key in configs", not re.search(r"sk-[A-Za-z0-9_\-]{12,}", claude + codex)),
    ]
    reach = "unreachable"
    if key:
        try:
            reach = f"{len(combo_entries(fetch_models(args.base_url, key), args.include_auto))} combos visible"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            reach = f"error: {type(exc).__name__}"
    for label, ok in checks:
        print(f"[{'ok' if ok else '--'}] {label}")
    print(f"gateway {args.base_url}: {reach}")
    return 0 if all(ok for _, ok in checks) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("OMNIROUTE_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--home", default=str(Path.home()))
    ap.add_argument("--bin-dir", default=str(Path.home() / ".local/bin"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--store-key", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--include-auto", action="store_true", help="also list OmniRoute's built-in auto/* virtual combos")
    args = ap.parse_args(argv)
    user = os.environ.get("USER") or Path(args.home).name
    if args.status:
        return cmd_status(args, user)
    if args.store_key:
        return cmd_store_key(user)
    if args.rollback:
        return cmd_rollback(args)
    if args.refresh:
        return cmd_refresh(args, user)
    if args.project:
        return cmd_project(args, user)
    return cmd_apply(args, user)


if __name__ == "__main__":
    sys.exit(main())

"""Deterministic onboarding stepper used by the TUI and by agents (--headless).

Wraps doctor / smoke / walk / graph-upgrade / onboard.py. Never enables hold/refuse.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
PYTHON = sys.executable or "python3"

# name, binaries to search, onboard.py --prompt runtime if that CLI runs the interview
AGENT_CLIS = (
    ("claude", ("claude",), "claude"),
    ("codex", ("codex",), "codex"),
    ("kimi", ("kimi", "kimi-cli"), "generic"),
)

STEPS = (
    "doctor",
    "smoke",
    "walk",
    "prompt",
    "harvest",
    "apply",
    "enable",
    "render",
    "graph-upgrade",
    "hermes",
)


def which(names: tuple[str, ...] | str) -> str | None:
    if isinstance(names, str):
        names = (names,)
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def detect_agent_clis() -> list[dict]:
    found = []
    for name, binaries, prompt_runtime in AGENT_CLIS:
        path = which(binaries)
        found.append({
            "name": name,
            "binaries": list(binaries),
            "path": path,
            "installed": bool(path),
            "prompt_runtime": prompt_runtime,
        })
    return found


def any_agent_cli() -> dict | None:
    for row in detect_agent_clis():
        if row["installed"]:
            return row
    return None


def resolve_mode(requested: str) -> dict:
    """requested is 'agent' or 'tui'. Agent without a CLI falls back to tui."""
    want = (requested or "tui").strip().lower()
    if want not in ("agent", "tui"):
        want = "tui"
    installed = detect_agent_clis()
    present = [r for r in installed if r["installed"]]
    if want == "agent" and not present:
        return {
            "requested": "agent",
            "mode": "tui",
            "fallback": True,
            "reason": "no claude, kimi/kimi-cli, or codex on PATH; using manual TUI flow",
            "clis": installed,
        }
    return {
        "requested": want,
        "mode": want,
        "fallback": False,
        "reason": "agent CLI present" if want == "agent" else "manual TUI flow",
        "clis": installed,
    }


def run_cmd(argv: list[str], *, cwd: Path | None = None, env: dict | None = None, timeout: int | None = None) -> dict:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        argv,
        cwd=str(cwd or ROOT),
        env=merged,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return {
        "argv": argv,
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "output": out.strip(),
    }


def step_doctor() -> dict:
    return {"id": "doctor", **run_cmd(["bash", str(SCRIPTS / "doctor.sh")])}


def step_smoke() -> dict:
    env = {"SNOWGLOVES_EMBED_BACKEND": os.environ.get("SNOWGLOVES_EMBED_BACKEND", "stub")}
    return {"id": "smoke", **run_cmd(["make", "smoke"], env=env, timeout=180)}


def step_walk() -> dict:
    return {"id": "walk", **run_cmd([PYTHON, str(SCRIPTS / "graph_walk.py")], timeout=120)}


def step_graph_upgrade_dry(tenant: str | None = None) -> dict:
    argv = [PYTHON, str(SCRIPTS / "graph_upgrade.py")]
    if tenant:
        argv += ["--tenant", tenant]
    return {"id": "graph-upgrade", **run_cmd(argv, timeout=60)}


def step_prompt(runtime: str) -> dict:
    return {"id": "prompt", **run_cmd([PYTHON, str(SCRIPTS / "onboard.py"), "--prompt", runtime])}


def step_apply(harvest: Path, tenant: str) -> dict:
    return {
        "id": "apply",
        **run_cmd([
            PYTHON, str(SCRIPTS / "onboard.py"),
            "--apply-harvest", str(harvest),
            "--tenant", tenant,
        ]),
    }


def step_enable(tenant: str, ids: str, replace: bool = False) -> dict:
    sys.path.insert(0, str(SCRIPTS))
    import onboard  # noqa: WPS433

    catalog = onboard.Catalog(ROOT, ROOT / "adapters")
    try:
        onboard.resolve_ids(catalog, [i.strip() for i in ids.split(",") if i.strip()])
    except SystemExit as exc:
        return {"id": "enable", "ok": False, "code": 2, "output": str(exc), "argv": ["--enable", ids]}
    argv = [PYTHON, str(SCRIPTS / "onboard.py"), "--enable", ids, "--tenant", tenant]
    if replace:
        argv.append("--replace")
    return {"id": "enable", **run_cmd(argv)}


def step_render(runtime: str, tenant: str, write: bool = False) -> dict:
    argv = [PYTHON, str(SCRIPTS / "onboard.py"), "--render-adapter", runtime, "--tenant", tenant]
    if write:
        argv.append("--write")
    return {"id": "render", **run_cmd(argv)}


def step_list_catalog(category: str | None = None) -> dict:
    argv = [PYTHON, str(SCRIPTS / "onboard.py"), "--list", "--json"]
    if category:
        argv += ["--category", category]
    return {"id": "list", **run_cmd(argv)}


def walk_receipt_path() -> Path:
    # `_demo` is a code fixture: graph_walk.py writes its receipt here even when $SNOWGLOVES_DATA is set
    return ROOT / "tenants" / "_demo" / "audit" / "graph-walk.json"


def load_walk_receipt() -> dict | None:
    path = walk_receipt_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def harvest_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def run_headless(opts: dict) -> dict:
    """Agent-safe pipeline. Never starts a TTY app. Never writes hooks."""
    requested = opts.get("mode") or "tui"
    resolved = resolve_mode(requested)
    mode = resolved["mode"]
    runtime = opts.get("runtime") or "cursor"
    tenant = opts.get("tenant")
    harvest = Path(opts["harvest"]) if opts.get("harvest") else ROOT / "snowgloves-harvest.md"
    enable_ids = opts.get("enable") or ""
    write = bool(opts.get("write"))
    skip = set(opts.get("skip") or [])
    results = []
    overall = True

    def take(row: dict) -> None:
        nonlocal overall
        results.append(row)
        overall = overall and bool(row.get("ok"))

    if "doctor" not in skip:
        take(step_doctor())
    if "smoke" not in skip:
        take(step_smoke())
    if "walk" not in skip:
        take(step_walk())
    if mode == "agent":
        take(step_prompt(runtime))
        if not harvest_ready(harvest):
            take({
                "id": "harvest",
                "ok": False,
                "code": 2,
                "output": f"agent mode: paste the prompt into {runtime} plan mode; waiting on {harvest}",
                "argv": [],
            })
            return {"ok": False, "mode": resolved, "steps": results}
        take({"id": "harvest", "ok": True, "code": 0, "output": str(harvest), "argv": []})
    elif harvest_ready(harvest) and tenant:
        take({"id": "harvest", "ok": True, "code": 0, "output": str(harvest), "argv": []})
    if tenant and harvest_ready(harvest) and "apply" not in skip:
        take(step_apply(harvest, tenant))
    if tenant and enable_ids and "enable" not in skip:
        take(step_enable(tenant, enable_ids))
    if tenant and runtime and "render" not in skip:
        take(step_render(runtime, tenant, write=write))
    if "graph-upgrade" not in skip:
        take(step_graph_upgrade_dry(tenant))
    receipt = load_walk_receipt()
    return {
        "ok": overall,
        "mode": resolved,
        "steps": results,
        "walk_verdict": (receipt or {}).get("verdict"),
        "hermes": "not started (headless); run make hermes in another process",
    }

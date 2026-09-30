#!/usr/bin/env python3
"""Snow Gloves onboarding TUI + headless runner for agents.

    make tui
    python3 scripts/tui_onboard.py                  # interactive: agent | TUI toggle
    python3 scripts/tui_onboard.py --headless --mode tui --skip smoke,hermes
    python3 scripts/tui_onboard.py --headless --mode agent --runtime claude --harvest snowgloves-harvest.md --tenant acme

Agent mode requires claude, kimi/kimi-cli, or codex on PATH; otherwise it falls back to TUI.
Does not enable hold/refuse. Does not auto-start Hermes in headless. graph-upgrade is dry-run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import tui_flow as flow  # noqa: E402

ROOT = flow.ROOT


def cmd_detect() -> int:
    rows = flow.detect_agent_clis()
    print(json.dumps({"clis": rows, "any": bool(flow.any_agent_cli())}, indent=2))
    return 0 if flow.any_agent_cli() else 1


def cmd_headless(ns: argparse.Namespace) -> int:
    skip = [s.strip() for s in (ns.skip or "").split(",") if s.strip()]
    receipt = flow.run_headless({
        "mode": ns.mode,
        "runtime": ns.runtime,
        "tenant": ns.tenant,
        "harvest": ns.harvest,
        "enable": ns.enable,
        "write": ns.write,
        "skip": skip,
    })
    print(json.dumps(receipt, indent=2, default=str))
    return 0 if receipt.get("ok") else 1


def simple_menu() -> int:
    """TTY stepper when Textual is missing. Same gates as the rich app."""
    print("Snow Gloves onboarding — manual TUI (Textual not installed; pip install -r requirements-tui.txt)")
    resolved = flow.resolve_mode(input("Mode [tui/agent] (default tui): ").strip() or "tui")
    print(json.dumps({k: resolved[k] for k in ("requested", "mode", "fallback", "reason")}, indent=2))
    runtime = input("Runtime prompt (cursor/claude/codex/generic, default cursor): ").strip() or "cursor"
    tenant = input("Tenant slug (blank to skip apply/enable/render): ").strip() or None
    harvest = Path(input("Harvest path [snowgloves-harvest.md]: ").strip() or "snowgloves-harvest.md")
    for name, fn in (
        ("doctor", flow.step_doctor),
        ("smoke", flow.step_smoke),
        ("walk", flow.step_walk),
    ):
        yn = input(f"Run {name}? [Y/n] ").strip().lower()
        if yn in ("", "y", "yes"):
            row = fn()
            print(row.get("output", "")[-2000:])
            print(f"==> {name}: {'ok' if row['ok'] else 'FAIL'} ({row['code']})")
    if resolved["mode"] == "agent":
        row = flow.step_prompt(runtime)
        print(row.get("output", "")[-4000:])
        print(f"Paste that into {runtime} plan mode. Harvest must land at {harvest}")
        input("Press Enter when snowgloves-harvest.md exists… ")
    if tenant and flow.harvest_ready(harvest):
        if input("Apply harvest? [Y/n] ").strip().lower() in ("", "y", "yes"):
            print(flow.step_apply(harvest, tenant).get("output", "")[-2000:])
        ids = input("Enable ids (comma, add|pointer only, blank skip): ").strip()
        if ids:
            print(flow.step_enable(tenant, ids).get("output", "")[-2000:])
        if input("Render dry-run? [Y/n] ").strip().lower() in ("", "y", "yes"):
            print(flow.step_render(runtime, tenant, write=False).get("output", "")[-2000:])
        if input("Render --write? [y/N] ").strip().lower() in ("y", "yes"):
            print(flow.step_render(runtime, tenant, write=True).get("output", "")[-2000:])
    print(flow.step_graph_upgrade_dry(tenant).get("output", "")[-2000:])
    rec = flow.load_walk_receipt()
    if rec:
        print(f"walk verdict: {rec.get('verdict')}")
    print("Leave Hermes up separately: make hermes")
    return 0


def textual_app(default_mode: str) -> int:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Input, Label, Log, Select, Static

    class OnboardApp(App):
        CSS = """
        Screen { layout: vertical; }
        #rail { height: 3; }
        #log { height: 1fr; border: solid cyan; }
        #row { height: auto; }
        """
        BINDINGS = [("q", "quit", "Quit")]

        def __init__(self, start_mode: str):
            super().__init__()
            self.start_mode = start_mode
            self.resolved = flow.resolve_mode(start_mode)

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static(self._rail(), id="rail")
            yield Horizontal(
                Vertical(
                    Label("Mode: agent needs claude, kimi, or codex CLI"),
                    Select(
                        (("Manual TUI", "tui"), ("Agent interview", "agent")),
                        value=self.resolved["mode"],
                        id="mode",
                    ),
                    Input(placeholder="runtime (cursor/claude/codex)", id="runtime", value="cursor"),
                    Input(placeholder="tenant slug", id="tenant"),
                    Input(placeholder="harvest path", id="harvest", value="snowgloves-harvest.md"),
                    Input(placeholder="enable ids (add|pointer only)", id="enable"),
                    id="row",
                )
            )
            yield Horizontal(
                Button("Doctor", id="doctor"),
                Button("Smoke", id="smoke"),
                Button("Walk", id="walk"),
                Button("Prompt", id="prompt"),
                Button("Apply", id="apply"),
                Button("Enable", id="enable_btn"),
                Button("Render dry", id="render"),
                Button("Render write", id="render_write"),
                Button("Upgrade dry", id="upgrade"),
                Button("Receipt", id="receipt"),
            )
            yield Log(id="log")
            yield Footer()

        def _rail(self) -> str:
            r = self.resolved
            clis = ",".join(c["name"] for c in r["clis"] if c["installed"]) or "none"
            return f"mode={r['mode']} fallback={r['fallback']} clis={clis} — {r['reason']}"

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id == "mode":
                self.resolved = flow.resolve_mode(str(event.value))
                self.query_one("#rail", Static).update(self._rail())
                if self.resolved["fallback"]:
                    self.query_one("#log", Log).write_line(self.resolved["reason"])

        def _val(self, wid: str) -> str:
            return self.query_one(f"#{wid}", Input).value.strip()

        def _run(self, row: dict) -> None:
            log = self.query_one("#log", Log)
            log.write_line(f"$ {' '.join(str(a) for a in row.get('argv') or [])}")
            log.write_line(row.get("output") or "")
            log.write_line(f"==> {row.get('id')}: {'ok' if row.get('ok') else 'FAIL'} ({row.get('code')})")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            bid = event.button.id
            runtime = self._val("runtime") or "cursor"
            tenant = self._val("tenant") or None
            harvest = Path(self._val("harvest") or "snowgloves-harvest.md")
            if bid == "doctor":
                self._run(flow.step_doctor())
            elif bid == "smoke":
                self._run(flow.step_smoke())
            elif bid == "walk":
                self._run(flow.step_walk())
            elif bid == "prompt":
                if self.resolved["mode"] == "agent" and not flow.any_agent_cli():
                    self.resolved = flow.resolve_mode("agent")
                    self.query_one("#rail", Static).update(self._rail())
                self._run(flow.step_prompt(runtime))
                self.query_one("#log", Log).write_line(
                    f"Run that prompt in plan mode. Harvest: {harvest}"
                )
            elif bid == "apply":
                if not tenant:
                    self.query_one("#log", Log).write_line("tenant slug required")
                    return
                if not flow.harvest_ready(harvest):
                    self.query_one("#log", Log).write_line(f"missing harvest {harvest}")
                    return
                self._run(flow.step_apply(harvest, tenant))
            elif bid == "enable_btn":
                ids = self._val("enable")
                if not tenant or not ids:
                    self.query_one("#log", Log).write_line("tenant and enable ids required")
                    return
                self._run(flow.step_enable(tenant, ids))
            elif bid == "render":
                if not tenant:
                    self.query_one("#log", Log).write_line("tenant required")
                    return
                self._run(flow.step_render(runtime, tenant, write=False))
            elif bid == "render_write":
                if not tenant:
                    self.query_one("#log", Log).write_line("tenant required")
                    return
                self._run(flow.step_render(runtime, tenant, write=True))
            elif bid == "upgrade":
                self._run(flow.step_graph_upgrade_dry(tenant))
            elif bid == "receipt":
                rec = flow.load_walk_receipt()
                self.query_one("#log", Log).write_line(json.dumps(rec, indent=2) if rec else "no walk receipt")

    OnboardApp(default_mode).run()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--headless", action="store_true", help="JSON pipeline for agents; no TTY app")
    p.add_argument("--mode", choices=("tui", "agent"), default="tui")
    p.add_argument("--runtime", default="cursor", help="onboard.py --prompt / --render-adapter runtime")
    p.add_argument("--tenant")
    p.add_argument("--harvest", help="path to snowgloves-harvest.md")
    p.add_argument("--enable", help="comma-separated add|pointer ids")
    p.add_argument("--write", action="store_true", help="render --write (headless)")
    p.add_argument("--skip", default="", help="comma step ids to skip (doctor,smoke,walk,apply,enable,render,graph-upgrade)")
    p.add_argument("--detect", action="store_true", help="print agent CLI detection JSON")
    p.add_argument("--simple", action="store_true", help="force numbered-menu TUI (no Textual)")
    ns = p.parse_args(argv)
    if ns.detect:
        return cmd_detect()
    if ns.headless:
        return cmd_headless(ns)
    if ns.simple:
        return simple_menu()
    try:
        import textual  # noqa: F401
    except ImportError:
        print("textual not installed; using simple menu. Optional: pip install -r requirements-tui.txt", file=sys.stderr)
        return simple_menu()
    return textual_app(ns.mode)


if __name__ == "__main__":
    raise SystemExit(main())

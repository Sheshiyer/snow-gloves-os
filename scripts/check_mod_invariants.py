#!/usr/bin/env python3
"""Check the Snow Gloves mods in mods/ against the platform's mod rules (docs/mods.md).

    I1  no tool.check hook, and no decision 'allow' anywhere
    I2  no hook answers a call with { result }: guards pass on with next(e) or refuse with { deny }
    I3  decisions stay human: no $.tool.register, no $.prompt.submit, no asUser
    I4  every tool.call hook is registered as on('tool.call', matcher, fn).catch(...)
    I5  $.http.fetch only in mods allowed to probe the platform's own endpoints
    I6  no $.fs.write and no $.process.spawn: mutations go through the platform's CLIs

Rules I1-I4 and I6 read the hooks module source. The calls each mod makes come from
`claude plugin validate --json`, which is the same static analysis Claude Code runs at load,
and must stay inside the mod's allowlist below. Without the `claude` binary the call check is
skipped with a note, unless --require-claude is given.

Exit codes: 0 clean, 1 a rule is broken, 2 validate failed or claude is missing when required.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODS = ROOT / "mods"

COMMON = {
    "$.clock.every", "$.clock.now", "$.clock.sleep", "$.command.register", "$.command.list", "$.command.run",
    "$.env.get", "$.fs.exists", "$.fs.read", "$.process.run", "$.session.cwd", "$.session.id", "$.session.surfaces",
    "$.state.get", "$.state.set", "$.ui.resolve", "$.ui.toast", "$.ui.log", "$.ui.open", "$.ui.ask",
}
ALLOWED_CALLS = {
    "sg-rail": COMMON | {"$.env.set", "$.http.fetch"},
    "sg-connector-gate": COMMON,
    "sg-approvals": COMMON,
}
FORBIDDEN_HOOKS = {"tool.check"}
SOURCE_RULES = [
    ("I1", re.compile(r"decision\s*:\s*['\"]allow['\"]"), "returns decision 'allow'"),
    ("I2", re.compile(r"return\s*\{\s*result\s*:"), "answers a call with { result }"),
    ("I3", re.compile(r"\$\.tool\.register|\$\.prompt\.submit|\basUser\b"), "lets the model or the mod decide for the user"),
    ("I6", re.compile(r"\$\.fs\.write|\$\.process\.spawn"), "writes files or spawns processes itself"),
]
TOOL_CALL = re.compile(r"on\(\s*['\"]tool\.call['\"]")
TOOL_CALL_CAUGHT = re.compile(r"on\(\s*['\"]tool\.call['\"][^\n]*\)\.catch\(")


def mod_dirs(base: Path) -> list[Path]:
    return sorted(p for p in base.iterdir() if (p / ".claude-plugin" / "plugin.json").is_file())


def sources(mod: Path) -> list[Path]:
    return sorted(p for p in (mod / "hooks").glob("*") if p.suffix in (".ts", ".tsx", ".js", ".mjs", ".jsx"))


def source_problems(mod: Path) -> list[str]:
    out = []
    for path in sources(mod):
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(ROOT)
        for rule, pattern, what in SOURCE_RULES:
            if pattern.search(text):
                out.append(f"{rule} {where}: {what}")
        if len(TOOL_CALL.findall(text)) != len(TOOL_CALL_CAUGHT.findall(text)):
            out.append(f"I4 {where}: a tool.call hook has no .catch on its registration line")
    if not list((mod / "tests").glob("*.test.ts*")):
        out.append(f"tests {mod.relative_to(ROOT)}: no *.test.ts file")
    return out


def validate(mod: Path, claude: str) -> tuple[dict | None, str]:
    run = subprocess.run([claude, "plugin", "validate", "--json", str(mod)], capture_output=True, text=True)
    try:
        return json.loads(run.stdout), ""
    except json.JSONDecodeError:
        return None, (run.stderr or run.stdout).strip()


def notes(report: dict, label: str) -> set[str]:
    """The names on a validate note line such as './register.ts calls: $.a, $.b (via f)'."""
    found: set[str] = set()
    for item in report.get("contents") or []:
        for note in item.get("notes") or []:
            head, _, rest = note.partition(f" {label}: ")
            if not rest or rest.strip() == "nothing":
                continue
            rest = re.sub(r"\s*\([^)]*\)", "", rest)  # drop "(via a, b)" before splitting on commas
            for part in rest.split(", "):
                found.add(part.split("{")[0].strip())
    return found


def call_problems(mod: Path, report: dict) -> list[str]:
    out = []
    name = mod.name
    if not report.get("success"):
        errors = [e for item in [report.get("manifest") or {}, *(report.get("contents") or [])] for e in item.get("errors") or []]
        out.append(f"validate {name}: " + "; ".join(str(e) for e in errors) or "failed")
    hooks = notes(report, "hooks")
    for hook in sorted(hooks & FORBIDDEN_HOOKS):
        out.append(f"I1 {name}: hooks {hook}")
    allowed = ALLOWED_CALLS.get(name)
    if allowed is None:
        out.append(f"calls {name}: no allowlist in scripts/check_mod_invariants.py")
        return out
    for call in sorted(notes(report, "calls") - allowed):
        rule = "I5" if call == "$.http.fetch" else "calls"
        out.append(f"{rule} {name}: calls {call}, which is not on its allowlist")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mods", type=Path, default=MODS)
    ap.add_argument("--require-claude", action="store_true")
    args = ap.parse_args(argv)
    claude = shutil.which("claude")
    if claude is None and args.require_claude:
        print("claude is not on PATH; it is needed for the calls check")
        return 2
    problems: list[str] = []
    for mod in mod_dirs(args.mods):
        problems += source_problems(mod)
        if claude is None:
            continue
        report, err = validate(mod, claude)
        if report is None:
            print(f"validate {mod.name}: {err}")
            return 2
        problems += call_problems(mod, report)
    if claude is None:
        print("note: claude is not on PATH, so the calls allowlist was not checked")
    for line in problems:
        print(line)
    print(f"{len(mod_dirs(args.mods))} mods checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

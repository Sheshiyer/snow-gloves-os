#!/usr/bin/env python3
"""Upgrade tenants to the platform VERSION.

  upgrade.py [--tenant slug] [--write]

For each tenant: read `tenants/<slug>/.snowgloves-version` (missing = 0.1), run
`migrations/v*_to_v*.py` in order against a scratch copy, then print a unified
diff. With `--write` the diff is applied, the catalog is rebuilt
(`scripts/build_catalog.py`) and the tenant's adapters are re-rendered
(`scripts/onboard.py --render-adapter <runtime> --write` per `runtime.yaml`).
Dry-run is the default.
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO / "migrations"
VERSION_FILE = ".snowgloves-version"
DEFAULT_VERSION = "0.1"
SKIP_DIRS = {"_embed_cache"}
_MIGRATION_NAME = re.compile(r"^v(\d+)_(\d+)_to_v(\d+)_(\d+)\.py$")


def mm(version: str) -> tuple[int, int]:
    parts = version.strip().lstrip("v").split(".")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def load_migrations(folder: Path = MIGRATIONS) -> list:
    mods = []
    for p in sorted(folder.glob("v*_to_v*.py")):
        if not _MIGRATION_NAME.match(p.name):
            continue
        spec = importlib.util.spec_from_file_location(f"sg_migration_{p.stem}", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mods.append(mod)
    return sorted(mods, key=lambda m: mm(m.FROM))


def tenant_version(tenant_dir: Path) -> str:
    f = tenant_dir / VERSION_FILE
    return f.read_text().strip() if f.exists() else DEFAULT_VERSION


def chain(current: str, target: str, migrations: list) -> list:
    """Migrations to run to go from `current` to `target` (gaps are no-ops)."""
    steps, cur = [], mm(current)
    for m in migrations:
        if mm(m.FROM) >= cur and mm(m.TO) <= mm(target):
            steps.append(m)
            cur = mm(m.TO)
    return steps


def _snapshot(root: Path) -> dict[str, bytes]:
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and not SKIP_DIRS.intersection(rel.parts):
            out[rel.as_posix()] = p.read_bytes()
    return out


def _text(b: bytes) -> list[str] | None:
    try:
        return b.decode("utf-8").splitlines(True)
    except UnicodeDecodeError:
        return None


def render_diff(slug: str, before: dict[str, bytes], after: dict[str, bytes]) -> str:
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    renames = {}
    for a in added:
        for r in removed:
            if r not in renames.values() and before[r] == after[a]:
                renames[a] = r
                break
    lines: list[str] = []
    base = f"tenants/{slug}"
    for new, old in renames.items():
        lines.append(f"rename {base}/{old} -> {base}/{new}\n")
    for rel in sorted(set(before) | set(after)):
        if rel in renames or rel in renames.values():
            continue
        old, new = before.get(rel), after.get(rel)
        if old == new:
            continue
        ot, nt = _text(old or b""), _text(new or b"")
        if ot is None or nt is None:
            lines.append(f"binary {base}/{rel} changed\n")
            continue
        lines.extend(difflib.unified_diff(
            ot, nt,
            f"a/{base}/{rel}" if old is not None else "/dev/null",
            f"b/{base}/{rel}" if new is not None else "/dev/null"))
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def apply(tenant_dir: Path, before: dict[str, bytes], after: dict[str, bytes]) -> None:
    for rel in set(before) - set(after):
        (tenant_dir / rel).unlink()
    for rel, data in after.items():
        if before.get(rel) != data:
            dst = tenant_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)


def upgrade_tenant(tenant_dir: Path, target: str, migrations: list, write: bool) -> tuple[str, list[str]]:
    current = tenant_version(tenant_dir)
    if mm(current) >= mm(target):
        return "", [f"{tenant_dir.name}: at {current}, nothing to do"]
    notes = [f"{tenant_dir.name}: {current} -> {target}"]
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / tenant_dir.name
        shutil.copytree(tenant_dir, scratch, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        for m in chain(current, target, migrations):
            notes += [f"  [{m.FROM}->{m.TO}] {n}" for n in m.migrate(scratch)]
        (scratch / VERSION_FILE).write_text(target + "\n")
        before, after = _snapshot(tenant_dir), _snapshot(scratch)
    diff = render_diff(tenant_dir.name, before, after)
    if write:
        apply(tenant_dir, before, after)
    return diff, notes


def runtimes_for(tenant_dir: Path) -> list[str]:
    f = tenant_dir / "runtime.yaml"
    if not f.exists():
        return []
    data = yaml.safe_load(f.read_text()) or {}
    if isinstance(data, dict):
        data = data.get("runtimes", data.get("runtime", []))
    if isinstance(data, str):
        data = [data]
    out = []
    for item in data or []:
        name = item.get("id") or item.get("name") if isinstance(item, dict) else item
        if isinstance(item, dict) and item.get("enabled") is False:
            continue
        if name:
            out.append(str(name))
    return out


def _run(cmd: list[str], root: Path, write: bool) -> None:
    print(("$ " if write else "[dry-run] would run: ") + " ".join(cmd))
    if write:
        r = subprocess.run(cmd, cwd=root)
        if r.returncode:
            print(f"  exit {r.returncode}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", help="tenant slug (default: all tenants)")
    ap.add_argument("--write", action="store_true", help="apply changes (default is dry-run)")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = a.root.resolve()
    vf = root / "VERSION"
    target = (vf if vf.exists() else REPO / "VERSION").read_text().strip()
    tenants_dir = root / "tenants"
    if a.tenant:
        dirs = [tenants_dir / a.tenant]
        if not dirs[0].is_dir():
            print(f"no such tenant: {a.tenant}", file=sys.stderr)
            return 2
    else:
        dirs = sorted(p for p in tenants_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    migrations = load_migrations()

    print(f"upgrade to platform {target} ({'write' if a.write else 'dry-run'})")
    for d in dirs:
        diff, notes = upgrade_tenant(d, target, migrations, a.write)
        print("\n".join(notes))
        if diff:
            sys.stdout.write(diff)

    py = sys.executable or "python3"
    if (root / "scripts" / "build_catalog.py").exists():
        _run([py, "scripts/build_catalog.py"], root, a.write)
    else:
        print("skip catalog refresh: scripts/build_catalog.py missing")
    if (root / "scripts" / "onboard.py").exists():
        for d in dirs:
            for rt in runtimes_for(d):
                cmd = [py, "scripts/onboard.py", "--render-adapter", rt, "--tenant", d.name]
                _run(cmd + ["--write"] if a.write else cmd, root, a.write)
    else:
        print("skip adapter render: scripts/onboard.py missing")
    if not a.write:
        print("\n[dry-run] nothing written; re-run with --write (make upgrade WRITE=1) to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

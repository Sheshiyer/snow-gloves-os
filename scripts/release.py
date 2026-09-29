#!/usr/bin/env python3
"""Platform release helper — keep every version file in lockstep with VERSION.

  release.py <x.y.z> [--dry-run] [--commit] [--tag]   bump + CHANGELOG section + catalog rebuild
  release.py --check [--expect vX.Y.Z]                  verify files agree (CI)
  release.py --bundle <dir>                             build platform release assets

Pushing is never done here; use `make release-push V=x.y.z`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")

PACKAGE_JSON = "apps/onboarding/package.json"
TAURI_CONF = "apps/onboarding/src-tauri/tauri.conf.json"
CARGO_TOML = "apps/onboarding/src-tauri/Cargo.toml"
PACKAGE_LOCK = "apps/onboarding/package-lock.json"
CARGO_LOCK = "apps/onboarding/src-tauri/Cargo.lock"
DISTRIBUTION = "distribution.yaml"
CRATE = "snowgloves-onboarding"
BUILD_CATALOG = "scripts/build_catalog.py"
CATALOG_OUTPUTS = ("catalog/modules.json", "catalog/registry.yaml")

_JSON_VERSION = re.compile(r'^(\s*"version"\s*:\s*")([^"]*)(")', re.M)
_YAML_VERSION = re.compile(r"^(version:\s*)([^\s#]+)(.*)$", re.M)
_CARGO_LOCK_VERSION = re.compile(rf'^(\[\[package\]\]\nname = "{CRATE}"\nversion = ")([^"]*)(")', re.M)


def _cargo_span(text: str) -> tuple[int, int] | None:
    """Span of the [package] version value; dependency versions are left alone."""
    m = re.search(r"^\[package\]\s*$", text, re.M)
    if not m:
        return None
    end = re.search(r"^\[", text[m.end():], re.M)
    section_end = m.end() + end.start() if end else len(text)
    v = re.compile(r'^version\s*=\s*"([^"]*)"', re.M).search(text, m.end(), section_end)
    return (v.start(1), v.end(1)) if v else None


def read_version(rel: str, text: str) -> str | None:
    if rel == "VERSION":
        return text.strip() or None
    if rel.endswith("Cargo.lock"):
        m = _CARGO_LOCK_VERSION.search(text)
        return m.group(2) if m else None
    if rel.endswith(".json"):
        m = _JSON_VERSION.search(text)
        return m.group(2) if m else None
    if rel.endswith("Cargo.toml"):
        span = _cargo_span(text)
        return text[span[0]:span[1]] if span else None
    if rel.endswith((".yaml", ".yml")):
        m = _YAML_VERSION.search(text)
        return m.group(2).strip("\"'") if m else None
    raise ValueError(rel)


def write_version(rel: str, text: str, version: str) -> str:
    if rel == "VERSION":
        return version + "\n"
    if rel.endswith("Cargo.lock"):
        return _CARGO_LOCK_VERSION.sub(lambda m: m.group(1) + version + m.group(3), text, count=1)
    if rel.endswith(".json"):
        # package-lock.json repeats the root version under packages[""]
        count = 2 if rel.endswith("package-lock.json") else 1
        return _JSON_VERSION.sub(lambda m: m.group(1) + version + m.group(3), text, count=count)
    if rel.endswith("Cargo.toml"):
        span = _cargo_span(text)
        if not span:
            raise ValueError(f"{rel}: no [package] version")
        return text[:span[0]] + version + text[span[1]:]
    if rel.endswith((".yaml", ".yml")):
        return _YAML_VERSION.sub(lambda m: m.group(1) + version + m.group(3), text, count=1)
    raise ValueError(rel)


def version_files(root: Path) -> list[str]:
    files = ["VERSION", PACKAGE_JSON, TAURI_CONF, CARGO_TOML]
    files += [rel for rel in (PACKAGE_LOCK, CARGO_LOCK, DISTRIBUTION) if (root / rel).exists()]
    return files


def current_versions(root: Path) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for rel in version_files(root):
        p = root / rel
        out[rel] = read_version(rel, p.read_text()) if p.exists() else None
    return out


def _read(p: Path) -> bytes | None:
    return p.read_bytes() if p.exists() else None


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def _changes_since_last_tag(root: Path) -> list[str]:
    try:
        last = _git(root, "describe", "--tags", "--abbrev=0", check=False).stdout.strip()
        rng = [f"{last}..HEAD"] if last else ["-n", "20"]
        log = _git(root, "log", "--no-merges", "--format=%s", *rng, check=False).stdout
    except FileNotFoundError:
        return []
    return [line for line in log.splitlines() if line and not line.startswith("release:")]


def changelog_update(text: str, version: str, today: str, notes: list[str]) -> str:
    """Finalize an existing `## vX (unreleased)` heading, or prepend a new section."""
    heading = re.compile(rf"^## v{re.escape(version)}\b.*$", re.M)
    m = heading.search(text)
    if m:
        line = m.group(0)
        if "(unreleased)" in line:
            line = line.replace("(unreleased)", f"({today})")
        return text[:m.start()] + line + text[m.end():]
    body = "\n".join(f"- {n}" for n in notes) or "- TODO: summarize this release."
    section = f"## v{version} — Release ({today})\n\n{body}\n\n"
    head = re.match(r"^# .*\n+", text)
    if head:
        return text[:head.end()] + section + text[head.end():]
    return "# Changelog\n\n" + section + text


def plan_bump(root: Path, version: str, today: str) -> dict[str, tuple[str, str]]:
    """rel path -> (old text, new text) for every file that would change."""
    changes: dict[str, tuple[str, str]] = {}
    for rel in version_files(root):
        p = root / rel
        old = p.read_text() if p.exists() else ""
        new = write_version(rel, old, version)
        if new != old:
            changes[rel] = (old, new)
    cl = root / "CHANGELOG.md"
    old = cl.read_text() if cl.exists() else ""
    new = changelog_update(old, version, today, _changes_since_last_tag(root))
    if new != old:
        changes["CHANGELOG.md"] = (old, new)
    return changes


def cmd_check(root: Path, expect: str | None) -> int:
    versions = current_versions(root)
    want = versions.get("VERSION")
    ok = True
    for rel, v in versions.items():
        mark = "ok" if v == want and v else "MISMATCH"
        ok &= mark == "ok"
        print(f"  {mark:8} {rel}: {v}")
    if expect is not None and expect.lstrip("v") != want:
        print(f"  MISMATCH tag {expect} != VERSION {want}")
        ok = False
    modules = root / "catalog" / "modules.json"
    if modules.exists():
        mv = json.loads(modules.read_text()).get("version")
        mark = "ok" if mv == want else "MISMATCH"
        ok &= mark == "ok"
        print(f"  {mark:8} catalog/modules.json: {mv}")
    cl = root / "CHANGELOG.md"
    if want and cl.exists() and not re.search(rf"^## v{re.escape(want)}\b", cl.read_text(), re.M):
        print(f"  MISMATCH CHANGELOG.md has no '## v{want}' section")
        ok = False
    print("version check:", "clean" if ok else "FAILED")
    return 0 if ok else 1


def cmd_bump(root: Path, version: str, dry_run: bool, commit: bool, tag: bool) -> int:
    if not SEMVER.match(version):
        print(f"not a semver version: {version}", file=sys.stderr)
        return 2
    today = dt.date.today().isoformat()
    changes = plan_bump(root, version, today)
    for rel, (old, new) in changes.items():
        sys.stdout.writelines(difflib.unified_diff(
            old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}"))
    catalog = root / BUILD_CATALOG
    if dry_run:
        if catalog.exists():
            print(f"[dry-run] would run: python3 {BUILD_CATALOG} (catalog/modules.json -> v{version})")
        print(f"\n[dry-run] {len(changes)} file(s) would change for v{version}; nothing written.")
        return 0
    for rel, (_, new) in changes.items():
        (root / rel).write_text(new)
    print(f"\nwrote {len(changes)} file(s) for v{version}")
    committed = list(changes)
    if catalog.exists():
        before = {rel: _read(root / rel) for rel in CATALOG_OUTPUTS}
        r = subprocess.run([sys.executable or "python3", str(catalog), "--root", str(root)], cwd=root)
        if r.returncode:
            print(f"{BUILD_CATALOG} failed (exit {r.returncode})", file=sys.stderr)
            return 1
        committed += [rel for rel in CATALOG_OUTPUTS if _read(root / rel) != before[rel]]
    else:
        print(f"skip catalog rebuild: {BUILD_CATALOG} missing")
    if commit and committed:
        _git(root, "add", "--", *committed)
        _git(root, "commit", "-m", f"release: v{version}", "--", *committed)
        print(f"committed release: v{version}")
    if tag:
        if _git(root, "rev-parse", "-q", "--verify", f"refs/tags/v{version}", check=False).returncode == 0:
            print(f"tag v{version} already exists", file=sys.stderr)
            return 1
        _git(root, "tag", "-a", f"v{version}", "-m", f"release: v{version}")
        print(f"tagged v{version} (not pushed) — push with: make release-push V={version}")
    return 0


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cmd_bundle(root: Path, outdir: Path) -> int:
    version = (root / "VERSION").read_text().strip()
    outdir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    src = outdir / f"snow-gloves-os-{version}-src.tar.gz"
    if (root / ".git").exists():
        _git(root, "archive", "--format=tar.gz", f"--prefix=snow-gloves-os-{version}/", "-o", str(src), "HEAD")
        made.append(src)
    else:
        print("skip source tarball: not a git checkout", file=sys.stderr)
    modules = root / "catalog" / "modules.json"
    if modules.exists():
        json.loads(modules.read_text())
        dst = outdir / "modules.json"
        dst.write_bytes(modules.read_bytes())
        made.append(dst)
    else:
        print("skip modules.json: catalog/modules.json missing", file=sys.stderr)
    adapters = root / "adapters"
    if adapters.is_dir():
        dst = outdir / f"snow-gloves-os-{version}-adapters.tar.gz"
        with tarfile.open(dst, "w:gz") as tf:
            tf.add(adapters, arcname="adapters")
        made.append(dst)
    else:
        print("skip adapters bundle: adapters/ missing", file=sys.stderr)
    sums = outdir / "SHA256SUMS"
    sums.write_text("".join(f"{_sha256(p)}  {p.name}\n" for p in made))
    for p in [*made, sums]:
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--expect", help="with --check: tag (vX.Y.Z) that VERSION must match")
    ap.add_argument("--commit", action="store_true", help="git commit the bumped files")
    ap.add_argument("--tag", action="store_true", help="create annotated tag vX.Y.Z (never pushes)")
    ap.add_argument("--bundle", type=Path, metavar="DIR", help="write platform release assets to DIR")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = a.root.resolve()
    if a.check:
        return cmd_check(root, a.expect)
    if a.bundle:
        return cmd_bundle(root, a.bundle)
    if not a.version:
        ap.error("version required (or --check / --bundle)")
    return cmd_bump(root, a.version.lstrip("v"), a.dry_run, a.commit, a.tag)


if __name__ == "__main__":
    sys.exit(main())

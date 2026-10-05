"""tenants/ hygiene: registry, manifests and context files stay consistent.

Runs against `paths.tenants_dir()`: this checkout's public fixtures when SNOWGLOVES_DATA is
unset (CI), the private data checkout's tenants when it is set. Portfolio-specific checks
(brand parents, retired brands) live with the data, not here.
"""
from pathlib import Path

import pytest
import yaml

from lib import paths

TENANTS = paths.tenants_dir()
REGISTRY = TENANTS / "_registry.yaml"

# _demo is a fixture tenant (sources.yaml, wiki, approvals) that predates MANIFEST.yaml.
NO_MANIFEST = {"_demo"}


def tenant_dirs() -> list[Path]:
    if not TENANTS.is_dir():
        return []
    return sorted(p for p in TENANTS.iterdir() if p.is_dir() and not p.name.startswith("."))


def registry_slugs() -> list[str]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    out = []
    for entry in data.get("tenants", []) or []:
        out.append(str(entry.get("slug") if isinstance(entry, dict) else entry))
    return out


def test_registry_exists():
    assert REGISTRY.is_file(), f"missing {REGISTRY}"


def test_every_tenant_dir_is_registered():
    missing = [d.name for d in tenant_dirs() if d.name not in registry_slugs()]
    assert missing == [], f"add to {REGISTRY}: {missing}"


def test_registry_has_no_phantom_entries():
    on_disk = {d.name for d in tenant_dirs()}
    phantom = [s for s in registry_slugs() if s not in on_disk]
    assert phantom == [], f"registered but no directory under {TENANTS}: {phantom}"


def test_registry_has_no_duplicates():
    slugs = registry_slugs()
    dupes = sorted({s for s in slugs if slugs.count(s) > 1})
    assert dupes == [], f"listed more than once in {REGISTRY}: {dupes}"


@pytest.mark.parametrize("tdir", tenant_dirs(), ids=lambda p: p.name)
def test_manifest_tenant_matches_dir(tdir: Path):
    manifest = tdir / "MANIFEST.yaml"
    if tdir.name in NO_MANIFEST:
        assert not manifest.exists() or yaml.safe_load(manifest.read_text(encoding="utf-8"))
        return
    assert manifest.is_file(), f"{tdir.name} has no MANIFEST.yaml (scripts/tenant_new.sh writes one)"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    assert data.get("tenant") == tdir.name, f"{manifest} names {data.get('tenant')!r}, directory is {tdir.name!r}"


def test_no_empty_context_files():
    empty = [
        str(f.relative_to(TENANTS))
        for tdir in tenant_dirs()
        for f in sorted((tdir / "context").glob("*.md"))
        if not f.read_text(encoding="utf-8").strip()
    ]
    assert empty == [], f"empty context files: {empty}"

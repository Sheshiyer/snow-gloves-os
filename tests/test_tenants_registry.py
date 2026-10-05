"""tenants/ hygiene: registry, manifests, portfolio blocks, and context files stay consistent."""
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TENANTS = ROOT / "tenants"
REGISTRY = TENANTS / "_registry.yaml"

# Portfolio confirmed by the founder on 2026-10-05: specs/006-editorial-steward-integration/founder-intake-2026-10-05.md.
AXTECH_BRANCHES = (
    "heyzack", "ecoled", "kartezzi", "izzimo", "wave-concept",
    "sunfeed", "cee-management", "china-sourcing", "metagration",
)
NESTED_BRANDS = {"axio": "metagration"}  # tenant -> parent tenant below Axtech
BRAND_TENANTS = ("axtech", *AXTECH_BRANCHES, *NESTED_BRANDS)
# Removed 2026-10-05: savewatt (dropped by the founder), iverif (now a project under cee-management).
RETIRED_TENANTS = ("savewatt", "iverif")
CONTEXT_FILES = ("company", "customer", "offer", "voice", "proof", "owner", "open-questions")

# _demo is a fixture tenant (sources.yaml, wiki, approvals) that predates MANIFEST.yaml; the registry says so.
NO_MANIFEST = {"_demo"}
# mathis predates scripts/tenant_new.sh and keys the slug as tenant_id; the registry says so.
SLUG_KEYS = ("tenant", "tenant_id")


def tenant_dirs() -> list[Path]:
    return sorted(p for p in TENANTS.iterdir() if p.is_dir())


def registry_slugs() -> list[str]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    return [str(s) for s in data.get("tenants", []) or []]


def test_every_tenant_dir_is_registered():
    missing = [d.name for d in tenant_dirs() if d.name not in registry_slugs()]
    assert missing == [], f"add to tenants/_registry.yaml: {missing}"


def test_registry_has_no_phantom_entries():
    on_disk = {d.name for d in tenant_dirs()}
    phantom = [s for s in registry_slugs() if s not in on_disk]
    assert phantom == [], f"registered but no directory: {phantom}"


def test_registry_has_no_duplicates():
    slugs = registry_slugs()
    assert len(slugs) == len(set(slugs))


@pytest.mark.parametrize("tdir", tenant_dirs(), ids=lambda p: p.name)
def test_manifest_tenant_matches_dir(tdir: Path):
    manifest = tdir / "MANIFEST.yaml"
    if tdir.name in NO_MANIFEST:
        assert not manifest.exists() or yaml.safe_load(manifest.read_text(encoding="utf-8"))
        return
    assert manifest.is_file(), f"{tdir.name} has no MANIFEST.yaml (scripts/tenant_new.sh writes one)"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    slug = next((data[k] for k in SLUG_KEYS if k in data), None)
    assert slug == tdir.name, f"{manifest.relative_to(ROOT)} names {slug!r}, directory is {tdir.name!r}"


@pytest.mark.parametrize("slug", BRAND_TENANTS)
def test_brand_tenant_has_portfolio_block(slug: str):
    data = yaml.safe_load((TENANTS / slug / "MANIFEST.yaml").read_text(encoding="utf-8")) or {}
    assert data.get("tenant") == slug
    assert data.get("isolation") == "strict"
    portfolio = data.get("portfolio")
    assert isinstance(portfolio, dict), f"{slug}: missing portfolio block"
    assert set(portfolio) >= {"root", "parent"}, f"{slug}: portfolio needs root and parent"
    brand = data.get("brand")
    assert isinstance(brand, dict) and "domain" in brand and "status" in brand, f"{slug}: missing brand block"


def test_axtech_branches_point_at_root():
    for slug in AXTECH_BRANCHES:
        data = yaml.safe_load((TENANTS / slug / "MANIFEST.yaml").read_text(encoding="utf-8"))
        assert data["portfolio"] == {"root": "axtech", "parent": "axtech"}, slug
    axtech = yaml.safe_load((TENANTS / "axtech" / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert axtech["portfolio"] == {"root": "axtech", "parent": None}


@pytest.mark.parametrize("slug,parent", sorted(NESTED_BRANDS.items()))
def test_nested_brands_point_at_their_parent(slug: str, parent: str):
    data = yaml.safe_load((TENANTS / slug / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert data["portfolio"] == {"root": "axtech", "parent": parent}, slug
    assert parent in BRAND_TENANTS


@pytest.mark.parametrize("slug", RETIRED_TENANTS)
def test_retired_tenants_are_gone(slug: str):
    assert not (TENANTS / slug).exists(), f"tenants/{slug} was retired on 2026-10-05"
    assert slug not in registry_slugs()


def test_portfolio_proposal_matches_tenants():
    proposal = json.loads(
        (ROOT / "specs/006-editorial-steward-integration/portfolio-map-proposal.json").read_text(encoding="utf-8")
    )
    branches = {b["id"]: b["parent"] for b in proposal["branches"]}
    expected = {slug: "axtech" for slug in AXTECH_BRANCHES} | NESTED_BRANDS
    assert branches == expected
    for project in proposal["projects"]:
        assert project["parent"] in BRAND_TENANTS, project["id"]
        assert project["id"] not in BRAND_TENANTS, f"{project['id']} is a project, not a tenant"


@pytest.mark.parametrize("slug", BRAND_TENANTS)
def test_brand_tenant_has_every_context_file(slug: str):
    missing = [name for name in CONTEXT_FILES if not (TENANTS / slug / "context" / f"{name}.md").is_file()]
    assert missing == [], f"{slug}: missing context files {missing}"


def test_no_context_file_is_empty():
    files = sorted(TENANTS.glob("*/context/*.md"))
    assert files, "no context files found under tenants/*/context/"
    empty = [str(f.relative_to(ROOT)) for f in files if not f.read_text(encoding="utf-8").strip()]
    assert empty == [], f"empty context files: {empty}"


def test_sources_files_parse():
    for slug in BRAND_TENANTS:
        data = yaml.safe_load((TENANTS / slug / "sources.yaml").read_text(encoding="utf-8")) or {}
        assert data.get("tenant") == slug
        assert isinstance(data.get("sources"), list)

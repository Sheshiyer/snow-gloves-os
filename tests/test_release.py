import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import release  # noqa: E402

FILES = [
    "VERSION", release.PACKAGE_JSON, release.TAURI_CONF, release.CARGO_TOML,
    release.PACKAGE_LOCK, release.CARGO_LOCK, release.DISTRIBUTION, "CHANGELOG.md",
]


@pytest.fixture
def root(tmp_path):
    for rel in FILES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dst)
    return tmp_path


def versions(root):
    return release.current_versions(root)


def test_repo_versions_are_consistent():
    assert release.main(["--check"]) == 0


def test_bump_syncs_every_file(root):
    assert release.main(["9.8.7", "--root", str(root)]) == 0
    assert set(versions(root).values()) == {"9.8.7"}
    lock = json.loads((root / release.PACKAGE_LOCK).read_text())
    assert lock["version"] == lock["packages"][""]["version"] == "9.8.7"
    assert release.main(["--check", "--root", str(root)]) == 0
    assert release.main(["--check", "--expect", "v9.8.7", "--root", str(root)]) == 0
    assert release.main(["--check", "--expect", "v9.8.6", "--root", str(root)]) == 1


def test_cargo_dependency_versions_untouched(root):
    before = (root / release.CARGO_TOML).read_text()
    release.main(["9.8.7", "--root", str(root)])
    after = (root / release.CARGO_TOML).read_text()
    assert before.count('version = "2"') == after.count('version = "2"') > 0
    assert after.count("9.8.7") == 1


def test_dry_run_writes_nothing(root, capsys):
    snap = {rel: (root / rel).read_text() for rel in FILES}
    assert release.main(["9.8.7", "--dry-run", "--root", str(root)]) == 0
    assert {rel: (root / rel).read_text() for rel in FILES} == snap
    assert "+9.8.7" in capsys.readouterr().out


def test_changelog_prepends_new_section(root):
    release.main(["9.8.7", "--root", str(root)])
    text = (root / "CHANGELOG.md").read_text()
    assert text.startswith("# Changelog\n\n## v9.8.7 — Release (")
    assert "## v0.1.0" in text


def test_changelog_finalizes_unreleased_heading():
    text = "# Changelog\n\n## v1.2.0 — Big one (unreleased)\n\n- x\n"
    out = release.changelog_update(text, "1.2.0", "2026-01-01", ["ignored"])
    assert out == "# Changelog\n\n## v1.2.0 — Big one (2026-01-01)\n\n- x\n"


def test_check_flags_mismatch(root):
    (root / "VERSION").write_text("0.0.1\n")
    assert release.main(["--check", "--root", str(root)]) == 1


def test_rejects_non_semver(root):
    assert release.main(["1.2", "--root", str(root)]) == 2


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_commit_and_tag_never_push(root):
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    assert release.main(["9.8.7", "--commit", "--tag", "--root", str(root)]) == 0
    tags = subprocess.run(["git", "-C", str(root), "tag"], capture_output=True, text=True).stdout.split()
    assert tags == ["v9.8.7"]
    remotes = subprocess.run(["git", "-C", str(root), "remote"], capture_output=True, text=True).stdout
    assert remotes == ""
    assert release.main(["9.8.7", "--tag", "--root", str(root)]) == 1


CATALOG_INPUTS = [
    release.BUILD_CATALOG, "skills/registry.yaml", "workflows/skill-hooks.yaml",
    "connectors/g-stack/capabilities.yaml",
]


@pytest.fixture
def catalog_root(root):
    for rel in CATALOG_INPUTS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    for rel in ("agents", "adapters", "catalog"):
        shutil.copytree(REPO / rel, root / rel)
    return root


def _catalog_check(root):
    return subprocess.run([sys.executable, str(root / release.BUILD_CATALOG), "--check", "--root", str(root)],
                          capture_output=True, text=True).returncode


def _modules_version(root):
    return json.loads((root / "catalog" / "modules.json").read_text())["version"]


def test_bump_rebuilds_catalog(catalog_root):
    assert _catalog_check(catalog_root) == 0
    assert release.main(["9.8.7", "--root", str(catalog_root)]) == 0
    assert _modules_version(catalog_root) == "9.8.7"
    assert _catalog_check(catalog_root) == 0
    assert release.main(["--check", "--root", str(catalog_root)]) == 0


def test_dry_run_leaves_catalog_alone(catalog_root, capsys):
    before = (catalog_root / "catalog" / "modules.json").read_bytes()
    assert release.main(["9.8.7", "--dry-run", "--root", str(catalog_root)]) == 0
    assert (catalog_root / "catalog" / "modules.json").read_bytes() == before
    assert f"would run: python3 {release.BUILD_CATALOG}" in capsys.readouterr().out


def test_check_flags_stale_catalog_version(catalog_root):
    (catalog_root / "catalog" / "modules.json").write_text('{"version": "0.0.1"}')
    assert release.main(["--check", "--root", str(catalog_root)]) == 1


def test_commit_includes_catalog(catalog_root):
    _git(catalog_root, "init", "-q")
    _git(catalog_root, "config", "user.email", "t@t")
    _git(catalog_root, "config", "user.name", "t")
    _git(catalog_root, "add", ".")
    _git(catalog_root, "commit", "-qm", "init")
    assert release.main(["9.8.7", "--commit", "--root", str(catalog_root)]) == 0
    dirty = subprocess.run(["git", "-C", str(catalog_root), "status", "--porcelain"],
                           capture_output=True, text=True).stdout
    assert dirty == ""


def test_bundle_assets(root, tmp_path_factory):
    (root / "catalog").mkdir()
    (root / "catalog" / "modules.json").write_text('{"modules": []}')
    (root / "adapters" / "generic").mkdir(parents=True)
    (root / "adapters" / "generic" / "adapter.yaml").write_text("schema: snowgloves.adapter.v1\n")
    out = tmp_path_factory.mktemp("dist")
    assert release.main(["--bundle", str(out), "--root", str(root)]) == 0
    v = (root / "VERSION").read_text().strip()
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted(["SHA256SUMS", "modules.json", f"snow-gloves-os-{v}-adapters.tar.gz"])
    assert "modules.json" in (out / "SHA256SUMS").read_text()

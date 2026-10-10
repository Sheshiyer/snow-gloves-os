import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_SCRIPT = ROOT / "scripts/package_pilot.py"


def package_at(directory):
    result = subprocess.run([sys.executable, "-B", str(PACKAGE_SCRIPT), "--output", str(directory)],
                            cwd=ROOT, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return directory


def install(source, prefix, *flags):
    return subprocess.run(["sh", str(source / "scripts/install-local.sh"), "--prefix", str(prefix), *flags],
                          cwd=ROOT, text=True, capture_output=True, timeout=20)


@pytest.fixture
def bundle(tmp_path):
    return package_at(tmp_path / "pilot")


def test_dry_run_has_no_side_effects_and_missing_parent_stays_missing(bundle, tmp_path):
    prefix = tmp_path / "never-created" / "nested" / "install"
    result = install(bundle, prefix, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"prefix": str(prefix), "status": "would-install"}
    assert not prefix.parent.parent.exists()


def test_dry_run_rejects_symlink_in_missing_prefix_ancestor(bundle, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    prefix = alias / "missing" / "install"
    result = install(bundle, prefix, "--dry-run")
    assert result.returncode == 1
    assert json.loads(result.stderr)["code"] == 1
    assert not (real / "missing").exists()


@pytest.mark.parametrize("where", ["scripts", "top-level"])
def test_installer_rejects_extra_bundle_members_before_prefix_creation(bundle, tmp_path, where):
    if where == "scripts":
        (bundle / "scripts/foreign.py").write_text("foreign")
    else:
        (bundle / "foreign.txt").write_text("foreign")
    prefix = tmp_path / "new-prefix"
    result = install(bundle, prefix)
    assert result.returncode == 1
    assert json.loads(result.stderr)["code"] == 1
    assert not prefix.exists()


def test_install_idempotency_and_launcher_work(bundle, tmp_path):
    prefix = tmp_path / "private-install"
    first = install(bundle, prefix)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["status"] == "installed"
    assert (prefix / "bin/snowgloves").stat().st_mode & 0o777 == 0o700
    assert (prefix / "VERSION").stat().st_mode & 0o777 == 0o600
    run_again = install(bundle, prefix)
    assert run_again.returncode == 0, run_again.stderr
    assert json.loads(run_again.stdout)["status"] == "already-installed"
    version = subprocess.run([str(prefix / "bin/snowgloves"), "--version"], text=True,
                             capture_output=True, timeout=15)
    assert version.returncode == 0
    assert version.stdout.strip()


def test_installer_preserves_foreign_existing_prefix_and_nested_additions(bundle, tmp_path):
    prefix = tmp_path / "installed"
    installed = install(bundle, prefix)
    assert installed.returncode == 0, installed.stderr
    foreign = prefix / "docs/foreign.md"
    foreign.write_text("retain this")
    before = foreign.read_bytes()
    retry = install(bundle, prefix)
    assert retry.returncode == 1
    assert json.loads(retry.stderr)["code"] == 1
    assert foreign.read_bytes() == before
    dry = install(bundle, prefix, "--dry-run")
    assert dry.returncode == 1
    assert foreign.read_bytes() == before


def test_installer_rejects_symlink_prefix_and_preserves_target(bundle, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "keep"
    sentinel.write_text("safe")
    prefix = tmp_path / "alias"
    prefix.symlink_to(target, target_is_directory=True)
    result = install(bundle, prefix)
    assert result.returncode == 1
    assert sentinel.read_text() == "safe"


def test_dry_run_with_missing_source_manifest_does_not_touch_prefix(bundle, tmp_path):
    (bundle / "SHA256SUMS").unlink()
    prefix = tmp_path / "never"
    result = install(bundle, prefix, "--dry-run")
    assert result.returncode == 1
    assert not prefix.exists()

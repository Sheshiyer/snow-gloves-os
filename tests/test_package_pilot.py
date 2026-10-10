import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tarfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_pilot as package


def run(*args):
    return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/package_pilot.py"), *map(str, args)],
                          cwd=ROOT, text=True, capture_output=True, timeout=15)


@pytest.fixture
def bundle(tmp_path):
    out = tmp_path / "pilot"
    result = run("--output", out)
    assert result.returncode == 0, result.stderr
    return out


def test_package_and_verify_emit_exact_manifest_and_tar_members(bundle):
    verify_result = run("--verify", bundle)
    assert verify_result.returncode == 0
    verify = json.loads(verify_result.stdout)
    assert verify["status"] == "verified"
    expected = set(package.PAYLOAD) | {package.MANIFEST}
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file() or p.is_symlink()}
    assert actual == expected
    manifest = (bundle / package.MANIFEST).read_text()
    for rel in package.PAYLOAD:
        digest, name = next(line.split("  ") for line in manifest.splitlines() if line.endswith("  " + rel))
        assert name == rel
        assert digest == hashlib.sha256((bundle / rel).read_bytes()).hexdigest()
    archive = pathlib.Path(str(bundle) + ".tar.gz")
    with tarfile.open(archive, "r:gz") as tar:
        assert set(tar.getnames()) == expected
        assert all(member.isfile() for member in tar.getmembers())


@pytest.mark.parametrize("mutation", ["missing", "extra", "nested-extra", "symlink", "tamper", "bad-manifest"])
def test_verify_rejects_incomplete_unsafe_or_tampered_package(bundle, mutation, tmp_path):
    # Copy a clean verified fixture so each mutation is isolated.
    target = tmp_path / "copy"
    import shutil
    shutil.copytree(bundle, target, symlinks=True)
    if mutation == "missing":
        (target / "docs/LOCAL-MINI-PILOT.md").unlink()
    elif mutation == "extra":
        (target / "extra.txt").write_text("foreign")
    elif mutation == "nested-extra":
        (target / "scripts/extra.py").write_text("foreign")
    elif mutation == "symlink":
        victim = target / "VERSION"
        content = victim.read_bytes()
        victim.unlink()
        victim.symlink_to(target / "SHA256SUMS")
        assert content
    elif mutation == "tamper":
        (target / "scripts/node_bootstrap.py").write_text("changed")
    else:
        (target / package.MANIFEST).write_text("0" * 64 + "  VERSION\n")
    result = run("--verify", target)
    assert result.returncode == 1
    error = json.loads(result.stderr)
    assert error["error"] == "package_operation_failed"
    assert "foreign" not in result.stderr and "VERSION" not in result.stderr


def test_package_refuses_existing_output_and_archive_without_clobber(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "sentinel"
    sentinel.write_text("keep")
    result = run("--output", out)
    assert result.returncode == 1
    assert sentinel.read_text() == "keep"

    archive = tmp_path / "fresh.tar.gz"
    archive.write_text("foreign archive")
    result2 = run("--output", tmp_path / "fresh")
    assert result2.returncode == 1
    assert archive.read_text() == "foreign archive"
    assert not (tmp_path / "fresh").exists()


def test_exclusive_directory_publication_preserves_raced_output(tmp_path, monkeypatch):
    out = tmp_path / "raced"
    real = package._rename_noreplace

    def race(srcfd, src, dstfd, dst):
        os.mkdir(dst, 0o700, dir_fd=dstfd)
        real(srcfd, src, dstfd, dst)

    monkeypatch.setattr(package, "_rename_noreplace", race)
    with pytest.raises(package.PackageError):
        package.package(str(out))
    assert out.is_dir()
    assert list(out.iterdir()) == []
    assert not pathlib.Path(str(out) + ".tar.gz").exists()


def test_verify_missing_path_and_invalid_cli_have_json_errors(tmp_path):
    missing = run("--verify", tmp_path / "missing")
    assert missing.returncode == 1
    assert json.loads(missing.stderr)["code"] == 1
    invalid = run("--verify", tmp_path, "--output", tmp_path / "x")
    assert invalid.returncode == 3
    assert json.loads(invalid.stderr)["code"] == 3

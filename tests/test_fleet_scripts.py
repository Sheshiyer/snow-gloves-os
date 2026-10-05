"""scripts/fleet/remote_access.sh and connect.sh against the placeholder fleet fixture.

The real inventory is instance data (private checkout); tests/fixtures/fleet.yaml mirrors
fleet.example.yaml with synthetic LAN names.

remote_access.sh must be a pure dry-run without --apply: exit 0 on this machine with no sudo,
print every command it would run, and create no files. connect.sh --print must resolve the
operator user and overlay name from the inventory.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "tests" / "fixtures" / "fleet.yaml"
REMOTE = ROOT / "scripts" / "fleet" / "remote_access.sh"
CONNECT = ROOT / "scripts" / "fleet" / "connect.sh"

WINGS = [
    ("marketing", "marketing-mac", "sg-marketing"),
    ("design", "design-mac", "sg-design"),
    ("coding", "coding-mac", "sg-coding"),
]


def _prepare(tmp_path: Path):
    """Create the scratch HOME first, then snapshot, so only the script's own writes would differ."""
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    return _snapshot(tmp_path)


def _run(args, cwd, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in ("SNOWGLOVES_FLEET", "SNOWGLOVES_DATA")}
    # Point HOME at a scratch dir so an accidental write would show up in the snapshot.
    env["HOME"] = str(Path(cwd) / "home")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", *map(str, args)], cwd=cwd, env=env, capture_output=True, text=True, timeout=120,
    )


def _snapshot(path: Path):
    return {p.relative_to(path) for p in path.rglob("*")}


def test_scripts_parse():
    for script in (REMOTE, CONNECT):
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("wing,hostname,operator", WINGS)
def test_remote_access_dry_run_per_wing(tmp_path, wing, hostname, operator):
    before = _prepare(tmp_path)
    res = _run([REMOTE, "--wing", wing, "--fleet", FLEET], cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "kickstart" in out
    assert "setremotelogin" in out
    assert f"scutil --set HostName {hostname}" in out
    assert f"-users sg-admin,{operator}" in out
    assert "sg-admin" in out and operator in out
    assert f"SNOWGLOVES_NODE {wing}" in out or f"SNOWGLOVES_NODE={wing}" in out
    assert "dry-run" in out
    # Nothing executed: every command line carries the dry-run marker, no "+ " applied marker.
    assert not any(line.startswith("+ ") for line in out.splitlines())
    assert _snapshot(tmp_path) == before


def test_remote_access_unknown_wing(tmp_path):
    before = _prepare(tmp_path)
    res = _run([REMOTE, "--wing", "warehouse", "--fleet", FLEET], cwd=tmp_path)
    assert res.returncode != 0
    assert "unknown wing" in res.stderr
    assert _snapshot(tmp_path) == before


def test_remote_access_requires_wing(tmp_path):
    res = _run([REMOTE, "--fleet", FLEET], cwd=tmp_path)
    assert res.returncode != 0
    assert "usage" in (res.stderr + res.stdout)


def test_remote_access_reads_env_fleet(tmp_path):
    res = _run([REMOTE, "--wing", "marketing"], cwd=tmp_path, extra_env={"SNOWGLOVES_FLEET": str(FLEET)})
    assert res.returncode == 0, res.stderr
    assert "marketing-mac" in res.stdout


def test_remote_access_missing_fleet(tmp_path):
    res = _run([REMOTE, "--wing", "coding", "--fleet", tmp_path / "nope.yaml"], cwd=tmp_path)
    assert res.returncode != 0
    assert "not found" in res.stderr


def test_connect_print_screen(tmp_path):
    res = _run([CONNECT, "coding", "--print", "--fleet", FLEET], cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    assert "vnc://sg-coding@coding-mac" in res.stdout
    assert res.stdout.strip().startswith("open ")


def test_connect_print_ssh(tmp_path):
    res = _run([CONNECT, "coding", "ssh", "--print", "--fleet", FLEET], cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "ssh sg-coding@coding-mac"


@pytest.mark.parametrize("wing,hostname,operator", WINGS)
def test_connect_print_every_wing_uses_env_fleet(tmp_path, wing, hostname, operator):
    res = _run([CONNECT, wing, "--print"], cwd=tmp_path, extra_env={"SNOWGLOVES_FLEET": str(FLEET)})
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == f"open vnc://{operator}@{hostname}"


def test_connect_unknown_wing(tmp_path):
    res = _run([CONNECT, "warehouse", "--print", "--fleet", FLEET], cwd=tmp_path)
    assert res.returncode != 0
    assert "unknown wing" in res.stderr


def test_connect_no_args(tmp_path):
    res = _run([CONNECT], cwd=tmp_path)
    assert res.returncode != 0


def test_connect_lan_uses_lan_host(tmp_path):
    res = _run([CONNECT, "coding", "ssh", "--print", "--lan", "--fleet", FLEET], cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "ssh sg-coding@coding-mac.local"

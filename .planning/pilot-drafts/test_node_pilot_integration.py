"""Controller acceptance of the real CLI across planning, mutation and recovery."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "node_bootstrap.py"


def invoke(*args):
    return subprocess.run(
        [sys.executable, "-B", str(CLI), *map(str, args)],
        capture_output=True, text=True, timeout=20,
    )


def write_plan(tmp_path):
    node_root = tmp_path / "node"
    node_root.mkdir()
    result = invoke("plan", "--root", node_root, "--node", "mini-test")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return node_root, path, plan


def test_cli_local_lifecycle(tmp_path):
    node_root, path, plan = write_plan(tmp_path)
    before = list(node_root.rglob("*"))
    inspected = invoke("inspect", "--root", node_root)
    assert inspected.returncode == 0, inspected.stderr
    assert list(node_root.rglob("*")) == before
    for operation in ("apply", "apply", "resume"):
        result = invoke(operation, "--plan", path, "--digest", plan["digest"])
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["profile_ready"] is False
    state = json.loads(invoke("status", "--root", node_root).stdout)
    assert state["state"] == "configured"
    doctor = invoke("doctor", "--root", node_root)
    assert doctor.returncode == 2, doctor.stderr
    assert json.loads(doctor.stdout)["profile_ready"] is False
    result = invoke("rollback", "--plan", path, "--digest", plan["digest"])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "rolled-back"
    for step in plan["steps"]:
        assert not (node_root / ".snowgloves-local" / step["path"]).exists()


def test_cli_wrong_digest_has_no_node_side_effect(tmp_path):
    node_root, path, plan = write_plan(tmp_path)
    result = invoke("apply", "--plan", path, "--digest", "0" * 64)
    assert result.returncode in (2, 3)
    assert not (node_root / ".snowgloves-local").exists()


def test_cli_rollback_preserves_drift(tmp_path):
    node_root, path, plan = write_plan(tmp_path)
    result = invoke("apply", "--plan", path, "--digest", plan["digest"])
    assert result.returncode == 0, result.stderr
    owned = node_root / ".snowgloves-local" / plan["steps"][0]["path"]
    owned.write_text("operator change\n")
    result = invoke("resume", "--plan", path, "--digest", plan["digest"])
    assert result.returncode == 2
    result = invoke("rollback", "--plan", path, "--digest", plan["digest"])
    assert result.returncode == 2
    assert owned.read_text() == "operator change\n"

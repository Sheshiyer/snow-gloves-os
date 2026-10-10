import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import node_bootstrap as bootstrap
import node_journal as journal


def run_cli(*args, cwd=None, env=None):
    child_env = os.environ.copy()
    child_env.pop("PYTHONDONTWRITEBYTECODE", None)
    if env:
        child_env.update(env)
    return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/node_bootstrap.py"), *map(str, args)],
                          cwd=cwd or ROOT, env=child_env, text=True, capture_output=True, timeout=10)


def parse_stdout(result):
    assert result.stdout.endswith("\n")
    return json.loads(result.stdout)


def test_source_digest_is_framed_and_stable():
    first = bootstrap.source_digest()
    assert first == bootstrap.source_digest()
    assert len(first) == 64
    h = hashlib.sha256()
    for label, path in (("VERSION", ROOT / "VERSION"),
                        ("scripts/node_bootstrap.py", ROOT / "scripts/node_bootstrap.py"),
                        ("scripts/node_journal.py", ROOT / "scripts/node_journal.py")):
        name, data = label.encode(), path.read_bytes()
        h.update(len(name).to_bytes(4, "big")); h.update(name)
        h.update(len(data).to_bytes(8, "big")); h.update(data)
    assert first == h.hexdigest()


def test_make_plan_is_deterministic_and_contract_shaped(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    one = bootstrap.make_plan(root.resolve(), "pilot-a")
    two = bootstrap.make_plan(root.resolve(), "pilot-a")
    assert one == two
    assert set(one) == {"schema", "node", "profile", "root", "source_digest", "steps", "held", "digest"}
    assert [step["path"] for step in one["steps"]] == ["node.json", "runtime.json", "OPERATIONS.md"]
    assert [step["depends_on"] for step in one["steps"]] == [[], ["identity"], ["runtime"]]
    assert one["digest"] == journal.digest_plan(one)
    assert "physical acceptance" in " ".join(one["held"])
    assert "disk" not in json.dumps(one["steps"])


def test_inspect_readonly_and_inventory_is_presence_only(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    before = sorted(p.name for p in root.iterdir())
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/" + name)
    info = bootstrap.inspect(root.resolve())
    assert sorted(p.name for p in root.iterdir()) == before
    assert info["machine"]
    assert info["tools"]["git"] == {"present": True, "path": "/usr/bin/git"}
    assert set(info["disk"]) == {"total_bytes", "used_bytes", "free_bytes"}


def test_cli_inspect_plan_and_readonly_status(tmp_path):
    root = tmp_path / "pilot"
    root.mkdir()
    inspect_result = run_cli("inspect", "--root", root)
    assert inspect_result.returncode == 0
    assert parse_stdout(inspect_result)["root"] == str(root)
    assert not (root / journal.STATE_DIR).exists()

    plan_result = run_cli("plan", "--root", root, "--node", "pilot-a")
    assert plan_result.returncode == 0
    plan = parse_stdout(plan_result)
    assert plan["digest"] == journal.digest_plan(plan)
    assert not (root / journal.STATE_DIR).exists()

    status_result = run_cli("status", "--root", root)
    assert status_result.returncode == 0
    assert parse_stdout(status_result) == {"state": "absent", "profile_ready": False}
    assert not (root / journal.STATE_DIR).exists()


def test_cli_lifecycle_held_doctor_debug_and_rollback(tmp_path):
    root = tmp_path / "pilot"
    root.mkdir()
    plan_file = tmp_path / "reviewed-plan.json"
    planned = run_cli("plan", "--root", root, "--node", "pilot-a")
    plan = parse_stdout(planned)
    plan_file.write_text(json.dumps(plan, separators=(",", ":")))

    before = run_cli("doctor", "--root", root)
    assert before.returncode == 1
    before_doc = parse_stdout(before)
    assert before_doc["status"] == "fail"
    assert before_doc["profile_ready"] is False

    applied = run_cli("apply", "--plan", plan_file, "--digest", plan["digest"])
    assert applied.returncode == 0, applied.stderr
    assert parse_stdout(applied)["state"] == "configured"
    doctor = run_cli("doctor", "--root", root)
    assert doctor.returncode == 2
    report = parse_stdout(doctor)
    assert report["status"] == "held"
    assert report["profile_ready"] is False
    assert all(f["observed_at"] and len(f["evidence_digest"]) == 64 for f in report["findings"])
    assert {f["status"] for f in report["findings"]} >= {"pass", "held"}

    debug = run_cli("debug", "collect", "--root", root,
                    env={"API_KEY": "test-secret-should-never-appear"})
    assert debug.returncode == 2
    debug_doc = parse_stdout(debug)
    assert "test-secret-should-never-appear" not in debug.stdout
    assert set(debug_doc) == {"schema", "root", "source_digest", "inventory", "journal", "findings", "profile_ready"}

    rolled = run_cli("rollback", "--plan", plan_file, "--digest", plan["digest"])
    assert rolled.returncode == 0, rolled.stderr
    assert parse_stdout(rolled)["state"] == "rolled-back"


def test_cli_resume_recovers_pending_local_write(tmp_path, monkeypatch):
    root = tmp_path / "pilot"
    root.mkdir()
    plan = bootstrap.make_plan(root.resolve(), "pilot-a")
    plan_file = tmp_path / "reviewed-plan.json"
    plan_file.write_text(json.dumps(plan))
    real = journal._atomic_json
    calls = [0]

    def interrupt_before_first_complete(statefd, value):
        calls[0] += 1
        if calls[0] == 3:
            raise RuntimeError("simulated interruption")
        return real(statefd, value)

    monkeypatch.setattr(journal, "_atomic_json", interrupt_before_first_complete)
    with pytest.raises(RuntimeError, match="simulated"):
        journal.apply(plan, plan["digest"])
    monkeypatch.setattr(journal, "_atomic_json", real)
    resumed = run_cli("resume", "--plan", plan_file, "--digest", plan["digest"])
    assert resumed.returncode == 0, resumed.stderr
    assert parse_stdout(resumed)["state"] == "configured"


def test_inspect_cli_does_not_create_bytecode(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "VERSION").write_bytes((ROOT / "VERSION").read_bytes())
    (bundle / "scripts/node_bootstrap.py").write_bytes((ROOT / "scripts/node_bootstrap.py").read_bytes())
    (bundle / "scripts/node_journal.py").write_bytes((ROOT / "scripts/node_journal.py").read_bytes())
    node_root = tmp_path / "node-root"
    node_root.mkdir()
    child = subprocess.run([sys.executable, str(bundle / "scripts/node_bootstrap.py"),
                            "inspect", "--root", str(node_root)], text=True, capture_output=True, timeout=10)
    assert child.returncode == 0
    assert not list((bundle / "scripts").glob("__pycache__"))
    assert not list(node_root.iterdir())


def test_stale_source_refuses_before_state_mutation(tmp_path, monkeypatch):
    root = tmp_path / "pilot"
    root.mkdir()
    plan = bootstrap.make_plan(root.resolve(), "pilot-a")
    plan["source_digest"] = "0" * 64
    plan["digest"] = journal.digest_plan(plan)
    plan_file = tmp_path / "stale.json"
    plan_file.write_text(json.dumps(plan))
    result = run_cli("apply", "--plan", plan_file, "--digest", plan["digest"])
    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == 2
    assert not (root / journal.STATE_DIR).exists()


def test_invalid_arguments_plan_json_symlink_and_node_exit_three(tmp_path):
    bad_args = run_cli("plan", "--root", tmp_path, "--node", "Bad Node")
    assert bad_args.returncode == 3
    assert json.loads(bad_args.stderr)["code"] == 3

    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schema":"x","schema":"y"}')
    result = run_cli("apply", "--plan", malformed, "--digest", "0" * 64)
    assert result.returncode == 3
    assert "schema" not in result.stderr

    real = tmp_path / "real-plan.json"
    real.write_text("{}")
    alias = tmp_path / "plan-link.json"
    alias.symlink_to(real)
    linked = run_cli("apply", "--plan", alias, "--digest", "0" * 64)
    assert linked.returncode == 3

    usage = run_cli("plan", "--unknown")
    assert usage.returncode == 3
    assert json.loads(usage.stderr)["error"] == "invalid_arguments"


def test_doctor_detects_local_content_drift_without_mutating(tmp_path):
    root = tmp_path / "pilot"
    root.mkdir()
    plan = bootstrap.make_plan(root.resolve(), "pilot-a")
    journal.apply(plan, plan["digest"])
    target = root / journal.STATE_DIR / "runtime.json"
    target.write_text("tampered")
    before = sorted(p.name for p in (root / journal.STATE_DIR).iterdir())
    result = run_cli("doctor", "--root", root)
    assert result.returncode == 1
    report = parse_stdout(result)
    runtime = next(item for item in report["findings"] if item["id"] == "local-runtime")
    assert runtime["status"] == "fail"
    assert sorted(p.name for p in (root / journal.STATE_DIR).iterdir()) == before


def test_deeply_nested_plan_fails_as_invalid_json_without_traceback(tmp_path):
    plan_file = tmp_path / "deep-plan.json"
    plan_file.write_text('[' * 2000 + '0' + ']' * 2000)
    result = run_cli("apply", "--plan", plan_file, "--digest", "0" * 64)
    assert result.returncode == 3
    assert json.loads(result.stderr)["code"] == 3
    assert not list(tmp_path.glob(".snowgloves-local"))


def test_launcher_help_version_and_invalid_shape():
    launcher = ROOT / "bin/snowgloves"
    help_result = subprocess.run([str(launcher), "--help"], text=True, capture_output=True, timeout=5)
    assert help_result.returncode == 0 and "Usage:" in help_result.stdout
    help_extra = subprocess.run([str(launcher), "--help", "extra"], text=True, capture_output=True, timeout=5)
    assert help_extra.returncode == 3
    version = subprocess.run([str(launcher), "--version"], text=True, capture_output=True, timeout=5)
    assert version.returncode == 0 and version.stdout.strip() == (ROOT / "VERSION").read_text().strip()
    invalid = subprocess.run([str(launcher), "unknown"], text=True, capture_output=True, timeout=5)
    assert invalid.returncode == 3
    assert json.loads(invalid.stderr)["code"] == 3

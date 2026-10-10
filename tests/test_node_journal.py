import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import node_journal as journal


def make_plan(root):
    plan = {
        "schema": "snowgloves.node-plan.v1",
        "node": "pilot-1",
        "profile": "local-pilot",
        "root": str(root),
        "source_digest": hashlib.sha256(b"source").hexdigest(),
        "steps": [
            {"id": "identity", "path": "node.json", "content": '{"node":"pilot-1"}\n', "depends_on": []},
            {"id": "runtime", "path": "runtime.json", "content": '{"runtime":"local"}\n', "depends_on": ["identity"]},
            {"id": "operations", "path": "OPERATIONS.md", "content": "Local operations\n", "depends_on": ["runtime"]},
        ],
        "held": ["external enrollment pending"],
    }
    plan["digest"] = journal.digest_plan(plan)
    return plan


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "node"
    path.mkdir(mode=0o700)
    return path.resolve()


def apply(plan, **kwargs):
    return journal.apply(plan, plan["digest"], **kwargs)


def test_plan_digest_closed_schema_and_binding(root):
    p = make_plan(root)
    assert journal.digest_plan(p) == p["digest"]
    altered = json.loads(json.dumps(p))
    altered["steps"][0]["path"] = "../outside"
    with pytest.raises(journal.BootstrapError):
        journal.digest_plan(altered)
    with pytest.raises(journal.BootstrapError):
        journal.apply(p, "0" * 64)
    assert journal.status(str(root)) == {"state": "absent", "profile_ready": False}
    assert not (root / journal.STATE_DIR).exists()


def test_apply_repeat_and_preserve_exact_preexisting_bytes(root):
    p = make_plan(root)
    target = root / journal.STATE_DIR / "node.json"
    (root / journal.STATE_DIR).mkdir()
    target.write_text(p["steps"][0]["content"])
    before = target.stat().st_ino
    result = apply(p)
    assert result["state"] == "configured"
    assert result["profile_ready"] is False
    assert result["held"] == p["held"]
    assert result["steps"][0]["owned"] is False
    assert apply(p)["state"] == "configured"
    assert target.stat().st_ino == before
    assert journal.rollback(p, p["digest"])["state"] == "rolled-back"
    assert target.read_text() == p["steps"][0]["content"]
    assert not (root / journal.STATE_DIR / "runtime.json").exists()


def test_resume_after_target_commit_before_receipt(root, monkeypatch):
    p = make_plan(root)
    real = journal._atomic_json
    calls = [0]

    def stop_after_file_commit(statefd, value):
        # Initial journal + pending receipt are persisted; interrupt on the
        # first completion receipt after its target was linked into place.
        calls[0] += 1
        if calls[0] == 3:
            raise RuntimeError("simulated interruption")
        return real(statefd, value)

    monkeypatch.setattr(journal, "_atomic_json", stop_after_file_commit)
    with pytest.raises(RuntimeError, match="simulated"):
        apply(p)
    monkeypatch.setattr(journal, "_atomic_json", real)
    result = apply(p, resume=True)
    assert result["state"] == "configured"
    assert result["steps"][0]["owned"] is True


@pytest.mark.parametrize("after_link", [False, True])
def test_sigkill_before_and_after_target_commit_resumes(root, after_link):
    p = make_plan(root)
    module_path = pathlib.Path(journal.__file__).resolve().parent
    code = (
        "import os,signal,sys;sys.path.insert(0,sys.argv[1]);import node_journal as j;"
        "real=j._link_noclobber;after=sys.argv[3]=='1';"
        "defn=None\n"
        "def stop(*a,**k):\n"
        "  if not after: os.kill(os.getpid(),signal.SIGKILL)\n"
        "  r=real(*a,**k)\n"
        "  if after: os.kill(os.getpid(),signal.SIGKILL)\n"
        "  return r\n"
        "j._link_noclobber=stop;j.apply(__import__('json').loads(open(sys.argv[2]).read()),sys.argv[4])"
    )
    plan_file = root / "plan.json"
    plan_file.write_text(json.dumps(p))
    child = subprocess.run([sys.executable, "-c", code, str(module_path), str(plan_file),
                            "1" if after_link else "0", p["digest"]], capture_output=True, timeout=5)
    assert child.returncode == -signal.SIGKILL
    result = apply(p, resume=True)
    assert result["state"] == "configured"
    assert result["steps"][0]["owned"] is True


def test_pending_publication_is_removed_by_rollback(root, monkeypatch):
    p = make_plan(root)
    real = journal._atomic_json
    calls = [0]

    def stop_before_complete(statefd, value):
        calls[0] += 1
        if calls[0] == 3:
            raise RuntimeError("simulated interruption")
        return real(statefd, value)

    monkeypatch.setattr(journal, "_atomic_json", stop_before_complete)
    with pytest.raises(RuntimeError):
        apply(p)
    monkeypatch.setattr(journal, "_atomic_json", real)
    target = root / journal.STATE_DIR / "node.json"
    assert target.exists()
    result = journal.rollback(p, p["digest"])
    assert result["state"] == "rolled-back"
    assert not target.exists()


@pytest.mark.parametrize("after_unlink", [False, True])
def test_interrupted_rollback_of_pending_publication_resumes(root, monkeypatch, after_unlink):
    p = make_plan(root)
    real_link = journal._link_noclobber

    def stop_after_link(*args, **kwargs):
        real_link(*args, **kwargs)
        raise RuntimeError("apply interrupted before receipt")

    monkeypatch.setattr(journal, "_link_noclobber", stop_after_link)
    with pytest.raises(RuntimeError):
        apply(p)
    monkeypatch.setattr(journal, "_link_noclobber", real_link)
    real_unlink = journal.os.unlink

    def interrupt_capture(path, *args, **kwargs):
        if path == "0.capture" and not after_unlink:
            raise RuntimeError("rollback interrupted before unlink")
        result = real_unlink(path, *args, **kwargs)
        if path == "0.capture":
            raise RuntimeError("rollback interrupted after unlink")
        return result

    monkeypatch.setattr(journal.os, "unlink", interrupt_capture)
    with pytest.raises(RuntimeError):
        journal.rollback(p, p["digest"])
    monkeypatch.setattr(journal.os, "unlink", real_unlink)
    assert journal.rollback(p, p["digest"])["state"] == "rolled-back"
    assert not (root / journal.STATE_DIR / "node.json").exists()
    assert not any((root / journal.STATE_DIR / "quarantine").iterdir())


def test_rollback_interruption_recovers_and_drift_is_preserved(root, monkeypatch):
    p = make_plan(root)
    apply(p)
    real_unlink = journal.os.unlink
    stopped = [False]

    def interrupt_after_unlink(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if path == "2.capture" and not stopped[0]:
            stopped[0] = True
            raise RuntimeError("simulated rollback interruption")
        return result

    monkeypatch.setattr(journal.os, "unlink", interrupt_after_unlink)
    with pytest.raises(RuntimeError, match="simulated"):
        journal.rollback(p, p["digest"])
    monkeypatch.setattr(journal.os, "unlink", real_unlink)
    assert journal.rollback(p, p["digest"])["state"] == "rolled-back"
    assert not (root / journal.STATE_DIR / "node.json").exists()

    p2 = make_plan(root / "other")
    (root / "other").mkdir()
    apply(p2)
    drift = root / "other" / journal.STATE_DIR / "node.json"
    drift.write_text("modified by someone else")
    with pytest.raises(journal.BootstrapError, match="drift|proof"):
        journal.rollback(p2, p2["digest"])
    assert drift.read_text() == "modified by someone else"
    assert journal.status(str(root / "other"))["state"] == "manual-recovery"


def test_tampered_journal_path_and_ownership_claim_rejected(root):
    p = make_plan(root)
    apply(p)
    jp = root / journal.STATE_DIR / "journal.json"
    doc = json.loads(jp.read_text())
    doc["steps"][0]["owned"] = False
    jp.write_text(json.dumps(doc))
    jp.chmod(0o600)
    with pytest.raises(journal.BootstrapError, match="altered"):
        apply(p)

    # A wrong plan cannot use the existing journal, even with a recomputed digest.
    p2 = make_plan(root)
    p2["steps"][0]["content"] = "different\n"
    p2["digest"] = journal.digest_plan(p2)
    with pytest.raises(journal.BootstrapError):
        apply(p2, resume=True)


def test_forged_owned_receipt_cannot_delete_preexisting_identical_file(root):
    p = make_plan(root)
    state = root / journal.STATE_DIR
    state.mkdir()
    target = state / "node.json"
    target.write_text(p["steps"][0]["content"])
    apply(p)
    jp = state / "journal.json"
    doc = json.loads(jp.read_text())
    doc["steps"][0]["owned"] = True
    jp.write_text(json.dumps(doc))
    jp.chmod(0o600)
    with pytest.raises(journal.BootstrapError):
        journal.rollback(p, p["digest"])
    assert target.read_text() == p["steps"][0]["content"]


def test_rollback_replacement_race_preserves_captured_foreign_file(root, monkeypatch):
    p = make_plan(root)
    apply(p)
    original_rename = journal.os.rename
    raced = [False]

    def replace_before_capture(src, dst, *args, **kwargs):
        if src == "OPERATIONS.md" and not raced[0]:
            raced[0] = True
            parentfd = kwargs["src_dir_fd"]
            original_rename(src, "saved-owned", src_dir_fd=parentfd, dst_dir_fd=parentfd)
            fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parentfd)
            os.write(fd, b"foreign replacement")
            os.close(fd)
        return original_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(journal.os, "rename", replace_before_capture)
    with pytest.raises(journal.BootstrapError):
        journal.rollback(p, p["digest"])
    monkeypatch.setattr(journal.os, "rename", original_rename)
    state = root / journal.STATE_DIR
    assert (state / "quarantine" / "2.capture").read_bytes() == b"foreign replacement"


def test_duplicate_json_key_and_symlink_paths_rejected(root):
    p = make_plan(root)
    apply(p)
    jp = root / journal.STATE_DIR / "journal.json"
    raw = jp.read_text()
    jp.write_text(raw[:-1] + ',"node":"different"}')
    jp.chmod(0o600)
    with pytest.raises(journal.BootstrapError, match="duplicate"):
        apply(p)

    parent = root.parent
    real = parent / "real-root"
    real.mkdir()
    alias = parent / "alias-root"
    alias.symlink_to(real, target_is_directory=True)
    p3 = make_plan(alias)
    p3["digest"] = journal.digest_plan(p3)
    with pytest.raises(journal.BootstrapError):
        apply(p3)


def test_no_clobber_foreign_target_and_symlink_target(root):
    p = make_plan(root)
    target = root / journal.STATE_DIR / "node.json"
    (root / journal.STATE_DIR).mkdir()
    target.write_text("foreign")
    with pytest.raises(journal.BootstrapError, match="clobber"):
        apply(p)
    assert target.read_text() == "foreign"

    target.unlink()
    other = root / "other"
    other.write_text(p["steps"][0]["content"])
    target.symlink_to(other)
    with pytest.raises(journal.BootstrapError):
        apply(p, resume=True)
    assert other.read_text() == p["steps"][0]["content"]


def test_no_clobber_publication_race_preserves_foreign_bytes(root, monkeypatch):
    p = make_plan(root)
    real = journal._link_noclobber
    raced = [False]

    def race(anchorfd, anchor, targetfd, target):
        if not raced[0]:
            raced[0] = True
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=targetfd)
            os.write(fd, b"foreign race")
            os.close(fd)
        return real(anchorfd, anchor, targetfd, target)

    monkeypatch.setattr(journal, "_link_noclobber", race)
    with pytest.raises(journal.BootstrapError) as err:
        apply(p)
    assert err.value.code == 2
    assert (root / journal.STATE_DIR / "node.json").read_bytes() == b"foreign race"


def test_nonblocking_subprocess_lock(root):
    p = make_plan(root)
    apply(p)
    state = root / journal.STATE_DIR
    code = "import fcntl,os,sys;fd=os.open(sys.argv[1],os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX);print('locked',flush=True);sys.stdin.read()"
    child = subprocess.Popen([sys.executable, "-c", code, str(state / ".lock")], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(journal.BootstrapError) as err:
            journal.rollback(p, p["digest"])
        assert err.value.code == 2
    finally:
        child.communicate("release", timeout=5)


@pytest.mark.parametrize("after_replace", [False, True])
def test_atomic_journal_interruption_exposes_only_complete_json(root, monkeypatch, after_replace):
    p = make_plan(root)
    apply(p)
    state = root / journal.STATE_DIR
    previous = json.loads((state / "journal.json").read_text())
    replacement = json.loads(json.dumps(previous))
    replacement["state"] = "manual-recovery"
    real_replace = journal.os.replace

    def interrupt(src, dst, *args, **kwargs):
        if after_replace:
            real_replace(src, dst, *args, **kwargs)
        raise RuntimeError("interrupted journal publication")

    fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(journal.os, "replace", interrupt)
    try:
        with pytest.raises(RuntimeError):
            journal._atomic_json(fd, replacement)
    finally:
        os.close(fd)
    current = json.loads((state / "journal.json").read_text())
    assert current == (replacement if after_replace else previous)
    assert not list(state.glob(".journal-*"))


def test_state_directory_symlink_rejected(root):
    outside = root.parent / "state-outside"
    outside.mkdir()
    (root / journal.STATE_DIR).symlink_to(outside, target_is_directory=True)
    p = make_plan(root)
    with pytest.raises(journal.BootstrapError):
        apply(p)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("bad", [None, [], {"x": 1}, {"schema": "x"}, float("nan")])
def test_status_rejects_malformed_journal_types(root, bad):
    state = root / journal.STATE_DIR
    state.mkdir(mode=0o700)
    (state / "journal.json").write_text(json.dumps(bad))
    (state / "journal.json").chmod(0o600)
    with pytest.raises(journal.BootstrapError):
        journal.status(str(root))

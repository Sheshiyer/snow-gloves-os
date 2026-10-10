"""Linux-only test suite for runtime remote cipher import contract."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
import time
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only contract")


def _resolve_module():
    repo_root = os.environ.get("SG_TEST_REPO_ROOT")
    if not repo_root:
        repo_root = str(pathlib.Path(__file__).resolve().parents[1])
    scripts_path = os.path.join(repo_root, "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    target_file = os.path.join(scripts_path, "lib", "runtime_remote_cipher_import.py")
    if not os.path.exists(target_file):
        target_file = os.path.join(repo_root, "runtime_remote_cipher_import.py")
    spec = importlib.util.spec_from_file_location("lib.runtime_remote_cipher_import", target_file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lib.runtime_remote_cipher_import"] = mod
    spec.loader.exec_module(mod)
    return mod


import_mod = _resolve_module()
import_remote_cipher_and_bind_journal = import_mod.import_remote_cipher_and_bind_journal

from lib.runtime_job_journal import LocalJobJournal
from lib.runtime_operation_identity import checkpoint_digest


@pytest.fixture
def owned_root():
    temp_dir = tempfile.mkdtemp(prefix="sg-test-remote-import-")
    real_dir = os.path.realpath(temp_dir)
    os.chmod(real_dir, 0o700)
    st = os.stat(real_dir)
    expected_id = (st.st_dev, st.st_ino, os.geteuid(), 0o700)
    yield real_dir, expected_id
    for f in os.listdir(real_dir):
        try:
            os.unlink(os.path.join(real_dir, f))
        except Exception:
            pass
    try:
        os.rmdir(real_dir)
    except Exception:
        pass


@pytest.fixture
def valid_setup(owned_root):
    root_path, expected_id = owned_root
    context = {
        "instanceId": "inst-import-001",
        "runtimeVersion": "3.8.50",
        "imageDigest": "b" * 64,
        "keyId": "key-import-01",
    }
    job_id = "0123456789abcdef0123456789abcdef"
    request_digest = checkpoint_digest(context, job_id)
    test_bytes = b"ENC-CIPHER-IMPORT-DATA-99999"
    sha = hashlib.sha256(test_bytes).hexdigest()
    record = {
        "schema": "sg.local-job.v1",
        "job_id": job_id,
        "request_digest": request_digest,
        "state": "artifact-verified",
        "artifact": {
            "leaf": f"sg-encrypted-{job_id}.bin",
            "bytes": len(test_bytes),
            "sha256": sha,
        },
    }
    key_prefix = f"cp/v1/{context['instanceId']}/{context['imageDigest']}/{job_id}/{request_digest}/{sha}"
    receipt = {
        "schema": "sg.remote-checkpoint.v1",
        "state": "remote-committed",
        "context": dict(context),
        "job_id": job_id,
        "request_digest": request_digest,
        "artifact": {
            "leaf": f"sg-encrypted-{job_id}.bin",
            "bytes": len(test_bytes),
            "sha256": sha,
        },
        "object_key": f"{key_prefix}.bin",
        "object_version": "v-remote-import-1.0",
        "commit_key": f"{key_prefix}.commit.json",
        "commit_version": "v-commit-import-1.0",
    }
    cancel_event = threading.Event()
    return root_path, expected_id, context, record, receipt, test_bytes, cancel_event


def _make_pipe_with_writer(data: bytes):
    r_fd, w_fd = os.pipe()
    fl = fcntl.fcntl(r_fd, fcntl.F_GETFL)
    fcntl.fcntl(r_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    def _writer():
        try:
            view = memoryview(data)
            while len(view) > 0:
                nw = os.write(w_fd, view)
                view = view[nw:]
        finally:
            os.close(w_fd)

    t = threading.Thread(target=_writer, daemon=True)
    t.start()
    return r_fd, t


def test_happy_path_cold_import(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        res = import_remote_cipher_and_bind_journal(
            root_path, expected_id, context, record, receipt, r_fd, cancel_event
        )
    finally:
        os.close(r_fd)
        writer_thread.join()

    assert res["schema"] == "sg.local-cipher-import.v1"
    assert res["state"] == "cipher-journal-bound"
    assert res["replay_stage"] is False
    assert res["replay_journal"] is False
    assert res["job_id"] == record["job_id"]
    assert res["request_digest"] == record["request_digest"]
    assert res["artifact"] == record["artifact"]
    assert res["context"] == context

    journal = LocalJobJournal(root_path)
    jrec = journal.lookup(record["job_id"], record["request_digest"])
    assert jrec is not None
    assert jrec["state"] == "artifact-verified"
    assert jrec["artifact"] == record["artifact"]


def test_full_replay_both_staged_and_journal_bound(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        res1 = import_remote_cipher_and_bind_journal(
            root_path, expected_id, context, record, receipt, r_fd, cancel_event
        )
    finally:
        os.close(r_fd)
        writer_thread.join()
    assert res1["replay_stage"] is False
    assert res1["replay_journal"] is False

    r_fd2, w_fd2 = os.pipe()
    fl = fcntl.fcntl(r_fd2, fcntl.F_GETFL)
    fcntl.fcntl(r_fd2, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    try:
        res2 = import_remote_cipher_and_bind_journal(
            root_path, expected_id, context, record, receipt, r_fd2, cancel_event
        )
    finally:
        os.close(r_fd2)
        os.close(w_fd2)

    assert res2["replay_stage"] is True
    assert res2["replay_journal"] is True
    assert res2["job_id"] == record["job_id"]


def test_prepared_unbound_journal_resumes_to_verified(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    journal = LocalJobJournal(root_path)
    prep = journal.prepare(record["job_id"], record["request_digest"])
    assert prep["state"] == "prepared"

    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        res = import_remote_cipher_and_bind_journal(
            root_path, expected_id, context, record, receipt, r_fd, cancel_event
        )
    finally:
        os.close(r_fd)
        writer_thread.join()

    assert res["replay_stage"] is False
    assert res["replay_journal"] is False
    final_j = journal.lookup(record["job_id"], record["request_digest"])
    assert final_j is not None
    assert final_j["state"] == "artifact-verified"


def test_staged_historical_cipher_with_prepared_journal(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    final_leaf_path = os.path.join(root_path, record["artifact"]["leaf"])
    with open(final_leaf_path, "wb") as f:
        f.write(test_bytes)
    os.chmod(final_leaf_path, 0o600)

    journal = LocalJobJournal(root_path)
    journal.prepare(record["job_id"], record["request_digest"])

    r_fd, w_fd = os.pipe()
    fl = fcntl.fcntl(r_fd, fcntl.F_GETFL)
    fcntl.fcntl(r_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    try:
        res = import_remote_cipher_and_bind_journal(
            root_path, expected_id, context, record, receipt, r_fd, cancel_event
        )
    finally:
        os.close(r_fd)
        os.close(w_fd)

    assert res["replay_stage"] is True
    assert res["replay_journal"] is False
    final_j = journal.lookup(record["job_id"], record["request_digest"])
    assert final_j is not None
    assert final_j["state"] == "artifact-verified"


def test_mismatched_verified_journal_artifact_held(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    final_leaf_path = os.path.join(root_path, record["artifact"]["leaf"])
    with open(final_leaf_path, "wb") as f:
        f.write(test_bytes)
    os.chmod(final_leaf_path, 0o600)

    other_leaf = f"sg-encrypted-{record['job_id']}.bin"
    jname = f"sg-job-{record['job_id']}.json"
    corrupt_rec = {
        "schema": "sg.local-job.v1",
        "job_id": record["job_id"],
        "request_digest": record["request_digest"],
        "state": "artifact-verified",
        "artifact": {
            "leaf": other_leaf,
            "bytes": len(test_bytes),
            "sha256": "f" * 64,
        },
    }
    with open(os.path.join(root_path, jname), "wb") as f:
        f.write(json.dumps(corrupt_rec, separators=(",", ":")).encode("utf-8"))
    os.chmod(os.path.join(root_path, jname), 0o600)

    r_fd, w_fd = os.pipe()
    fl = fcntl.fcntl(r_fd, fcntl.F_GETFL)
    fcntl.fcntl(r_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    try:
        with pytest.raises(RuntimeError, match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(
                root_path, expected_id, context, record, receipt, r_fd, cancel_event
            )
    finally:
        os.close(r_fd)
        os.close(w_fd)


def test_cancelled_before_and_at_gaps(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    cancel_event.set()
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        with pytest.raises(RuntimeError, match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(
                root_path, expected_id, context, record, receipt, r_fd, cancel_event
            )
    finally:
        os.close(r_fd)
        writer_thread.join()


def test_invalid_cancel_event_type_held(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        with pytest.raises(RuntimeError, match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(
                root_path, expected_id, context, record, receipt, r_fd, None
            )
    finally:
        os.close(r_fd)
        writer_thread.join()


def test_root_identity_tamper_at_gap_held(valid_setup, monkeypatch):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    stage_orig = import_mod.stage_remote_cipher

    def _stage_and_tamper(*args, **kwargs):
        res = stage_orig(*args, **kwargs)
        os.chmod(root_path, 0o755)
        return res

    monkeypatch.setattr(import_mod, "stage_remote_cipher", _stage_and_tamper)
    try:
        with pytest.raises(RuntimeError, match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(
                root_path, expected_id, context, record, receipt, r_fd, cancel_event
            )
    finally:
        os.close(r_fd)
        writer_thread.join()


def test_caller_mutation_isolation(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        res = import_remote_cipher_and_bind_journal(
            root_path, expected_id, context, record, receipt, r_fd, cancel_event
        )
    finally:
        os.close(r_fd)
        writer_thread.join()

    res["artifact"]["leaf"] = "mutated"
    res["context"]["keyId"] = "mutated-key"
    assert record["artifact"]["leaf"] != "mutated"
    assert context["keyId"] != "mutated-key"


def test_lock_contention_held_immediately(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    lock_fd = os.open(root_path, os.O_DIRECTORY)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        with pytest.raises(RuntimeError, match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(
                root_path, expected_id, context, record, receipt, r_fd, cancel_event
            )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        os.close(r_fd)
        writer_thread.join()


def test_clock_expired_after_stage_prevents_journal(valid_setup, monkeypatch):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    clock_orig = import_mod.time.monotonic
    stage_orig = import_mod.stage_remote_cipher
    staged_done = []

    def _stage_and_expire(*args, **kwargs):
        res = stage_orig(*args, **kwargs)
        staged_done.append(True)
        return res

    monkeypatch.setattr(import_mod, "stage_remote_cipher", _stage_and_expire)
    monkeypatch.setattr(import_mod.time, "monotonic", lambda: clock_orig() + (30.0 if staged_done else 0.0))
    try:
        with pytest.raises(RuntimeError, match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(
                root_path, expected_id, context, record, receipt, r_fd, cancel_event
            )
        assert staged_done
        jname = f"sg-job-{record['job_id']}.json"
        assert not os.path.exists(os.path.join(root_path, jname))
    finally:
        os.close(r_fd)
        writer_thread.join()


def test_peer_verified_binding_during_prepare_is_valid_replay(valid_setup, monkeypatch):
    root, expected, ctx, record, receipt, data, event = valid_setup
    original_prepare = LocalJobJournal.prepare
    original_record = LocalJobJournal.record_artifact

    def peer_prepare(self, job, digest):
        original_prepare(self, job, digest)
        a = record["artifact"]
        original_record(self, job, digest, a["leaf"], a["bytes"], a["sha256"])
        return original_prepare(self, job, digest)

    monkeypatch.setattr(LocalJobJournal, "prepare", peer_prepare)
    r, t = _make_pipe_with_writer(data)
    try:
        result = import_remote_cipher_and_bind_journal(root, expected, ctx, record, receipt, r, event)
    finally:
        os.close(r)
        t.join(2)
    assert result["state"] == "cipher-journal-bound"
    assert LocalJobJournal(root).lookup(record["job_id"], record["request_digest"]) == record


def test_final_journal_result_full_identity_must_match(valid_setup, monkeypatch):
    root, expected, ctx, record, receipt, data, event = valid_setup
    original_lookup = LocalJobJournal.lookup
    calls = []

    def faulty_readback(self, job, digest):
        result = original_lookup(self, job, digest)
        calls.append(result)
        if result is not None:
            result = dict(result)
            result["request_digest"] = "f" * 64
        return result

    monkeypatch.setattr(LocalJobJournal, "lookup", faulty_readback)
    r, t = _make_pipe_with_writer(data)
    try:
        with pytest.raises(RuntimeError, match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(root, expected, ctx, record, receipt, r, event)
    finally:
        os.close(r)
        t.join(2)
    assert len(calls) == 2


def test_boolean_artifact_size_in_final_journal_return_is_held(valid_setup, monkeypatch):
 root,expected,ctx,record,receipt,data,event=valid_setup
 data=b'x';sha=hashlib.sha256(data).hexdigest();record['artifact']['bytes']=1;record['artifact']['sha256']=sha;receipt['artifact']=dict(record['artifact']);prefix=f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/{record['job_id']}/{record['request_digest']}/{sha}";receipt['object_key']=prefix+'.bin';receipt['commit_key']=prefix+'.commit.json'
 original=LocalJobJournal.lookup
 def faulty(self,job,digest):
  result=original(self,job,digest)
  if result is not None and result['state']=='artifact-verified':
   result=dict(result);result['artifact']=dict(result['artifact']);result['artifact']['bytes']=True
  return result
 monkeypatch.setattr(LocalJobJournal,'lookup',faulty)
 r,t=_make_pipe_with_writer(data)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher import held$'):
   import_remote_cipher_and_bind_journal(root,expected,ctx,record,receipt,r,event)
 finally:os.close(r);t.join(2)


def _cold_import(setup):
 root,expected,ctx,record,receipt,data,event=setup;r,t=_make_pipe_with_writer(data)
 try:return import_remote_cipher_and_bind_journal(root,expected,ctx,record,receipt,r,event)
 finally:os.close(r);t.join(2)


def _replay_import(setup):
 root,expected,ctx,record,receipt,data,event=setup;r,w=os.pipe();os.set_blocking(r,False);os.write(w,b'caller-unconsumed')
 try:
  result=import_remote_cipher_and_bind_journal(root,expected,ctx,record,receipt,r,event)
  assert os.read(r,64)==b'caller-unconsumed'
  return result
 finally:os.close(r);os.close(w)


def test_verified_replay_at_capacity_has_no_allocation(valid_setup):
 root,expected,ctx,record,receipt,data,event=valid_setup
 _cold_import(valid_setup);leaf=pathlib.Path(root)/record['artifact']['leaf'];inode=leaf.stat().st_ino
 filler=pathlib.Path(root)/'unknown-capacity.bin'
 with filler.open('wb') as f:f.truncate(536870912)
 filler.chmod(0o600);before={p.name:(p.stat().st_ino,p.stat().st_size) for p in pathlib.Path(root).iterdir()}
 result=_replay_import(valid_setup)
 assert result['replay_stage'] and result['replay_journal'] and leaf.stat().st_ino==inode
 assert before=={p.name:(p.stat().st_ino,p.stat().st_size) for p in pathlib.Path(root).iterdir()}


def test_unbound_cipher_replay_requires_admission_before_journal(valid_setup):
 root,expected,ctx,record,receipt,data,event=valid_setup
 leaf=pathlib.Path(root)/record['artifact']['leaf'];leaf.write_bytes(data);leaf.chmod(0o600)
 filler=pathlib.Path(root)/'unknown-capacity.bin'
 with filler.open('wb') as f:f.truncate(536870912)
 filler.chmod(0o600)
 with pytest.raises(RuntimeError,match='^Remote cipher import held$'):_replay_import(valid_setup)
 assert not list(pathlib.Path(root).glob('sg-job-*.json'))
 assert leaf.read_bytes()==data


def test_cancel_after_real_journal_commit_holds_ack_retains_verified(valid_setup,monkeypatch):
 root,expected,ctx,record,receipt,data,event=valid_setup;original=LocalJobJournal.record_artifact
 def canceled(self,*args):
  result=original(self,*args);event.set();return result
 monkeypatch.setattr(LocalJobJournal,'record_artifact',canceled)
 with pytest.raises(RuntimeError,match='^Remote cipher import held$'):_cold_import(valid_setup)
 assert LocalJobJournal(root).lookup(record['job_id'],record['request_digest'])==record


def test_failure_after_real_journal_commit_is_unknown_not_rollback(valid_setup,monkeypatch):
 root,expected,ctx,record,receipt,data,event=valid_setup;original=LocalJobJournal.record_artifact
 def failed(self,*args):
  original(self,*args);raise OSError('OWNED DIAGNOSTIC')
 monkeypatch.setattr(LocalJobJournal,'record_artifact',failed)
 with pytest.raises(RuntimeError,match='^Remote cipher import held$'):_cold_import(valid_setup)
 assert LocalJobJournal(root).lookup(record['job_id'],record['request_digest'])==record


def test_cancel_between_stage_and_journal_has_no_journal(valid_setup,monkeypatch):
 root,expected,ctx,record,receipt,data,event=valid_setup;original=import_mod.stage_remote_cipher
 def stage(*args,**kwargs):
  result=original(*args);event.set();return result
 monkeypatch.setattr(import_mod,'stage_remote_cipher',stage)
 with pytest.raises(RuntimeError,match='^Remote cipher import held$'):_cold_import(valid_setup)
 assert (pathlib.Path(root)/record['artifact']['leaf']).read_bytes()==data
 assert not list(pathlib.Path(root).glob('sg-job-*.json'))


def test_caller_mutation_during_stage_does_not_change_bound_identity(valid_setup,monkeypatch):
 root,expected,ctx,record,receipt,data,event=valid_setup;original=import_mod.stage_remote_cipher
 expected_ctx=dict(ctx);expected_record=json.loads(json.dumps(record))
 def stage(*args,**kwargs):
  ctx['keyId']='mutated-key';record['job_id']='f'*32;record['artifact']['bytes']=999;receipt['object_version']='changed'
  return original(*args,**kwargs)
 monkeypatch.setattr(import_mod,'stage_remote_cipher',stage)
 result=_cold_import(valid_setup)
 assert result['context']==expected_ctx and result['artifact']==expected_record['artifact']
 assert LocalJobJournal(root).lookup(expected_record['job_id'],expected_record['request_digest'])==expected_record


def test_malformed_receipt_before_stage_has_no_effects(valid_setup):
 root,expected,ctx,record,receipt,data,event=valid_setup;receipt['artifact']['bytes']=True
 with pytest.raises(RuntimeError,match='^Remote cipher import held$'):_cold_import(valid_setup)
 assert os.listdir(root)==[]


def test_root_replacement_during_journal_constructor_has_no_journal(valid_setup,monkeypatch):
 root,expected,ctx,record,receipt,data,event=valid_setup;original=import_mod.LocalJobJournal;moved=root+'-original'
 def replaced(path):
  os.rename(root,moved);os.mkdir(root,0o700);return original(path)
 monkeypatch.setattr(import_mod,'LocalJobJournal',replaced)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher import held$'):_cold_import(valid_setup)
  assert os.listdir(root)==[] and not list(pathlib.Path(moved).glob('sg-job-*.json'))
 finally:
  if os.path.isdir(moved):os.rmdir(root);os.rename(moved,root)


def test_cancel_observer_fault_is_redacted_in_final_cleanup(valid_setup):
 root,expected,ctx,record,receipt,data,event=valid_setup
 def broken():raise OSError('OWNED DIAGNOSTIC')
 event.is_set=broken
 with pytest.raises(RuntimeError,match='^Remote cipher import held$'):_cold_import(valid_setup)
 assert os.listdir(root)==[]

# Independent caller deadline cases use existing real metadata and owned root fixtures.
def _deadline_pipe(data):
    readfd,writefd=os.pipe()
    os.set_blocking(readfd,False)
    try:
        assert os.write(writefd,data)==len(data)
    finally:
        os.close(writefd)
    return readfd

@pytest.mark.parametrize("value", [True,False,float("nan"),float("inf"),float("-inf"),100.0,99.0,115.01,type("I",(int,),{})(105),type("F",(float,),{})(105)])
def test_caller_deadline_invalid_before_root(value,valid_setup,monkeypatch):
    root,identity,ctx,rec,receipt,data,event=valid_setup
    fd=_deadline_pipe(data)
    monkeypatch.setattr(import_mod.time,"monotonic",lambda:100.0)
    calls=[]
    monkeypatch.setattr(import_mod,"_verify_root_guard",lambda *args:calls.append(args))
    try:
        with pytest.raises(RuntimeError,match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(root,identity,ctx,rec,receipt,fd,event,deadline=value)
        assert calls==[]
        assert os.listdir(root)==[]
        assert os.read(fd,100)==data
    finally:os.close(fd)

@pytest.mark.parametrize("explicit",[False,True])
def test_caller_deadline_propagates_real_stage(explicit,valid_setup,monkeypatch):
    root,identity,ctx,rec,receipt,data,event=valid_setup
    fd=_deadline_pipe(data)
    monkeypatch.setattr(import_mod.time,"monotonic",lambda:100.0)
    real=import_mod.stage_remote_cipher
    observed=[]
    def spy(*args,**kwargs):
        observed.append(kwargs["deadline"])
        return real(*args,**kwargs)
    monkeypatch.setattr(import_mod,"stage_remote_cipher",spy)
    try:
        options={"deadline":105.0} if explicit else {}
        result=import_remote_cipher_and_bind_journal(root,identity,ctx,rec,receipt,fd,event,**options)
        assert observed==[105.0 if explicit else 115.0]
        assert result["replay_stage"] is False and result["replay_journal"] is False
        assert pathlib.Path(root,rec["artifact"]["leaf"]).read_bytes()==data
    finally:os.close(fd)

def test_caller_deadline_clock_redaction(valid_setup,monkeypatch):
    import traceback
    root,identity,ctx,rec,receipt,data,event=valid_setup
    fd=_deadline_pipe(data)
    def boom():raise ValueError("SECRET-CLOCK")
    monkeypatch.setattr(import_mod.time,"monotonic",boom)
    try:
        with pytest.raises(RuntimeError,match="^Remote cipher import held$") as caught:
            import_remote_cipher_and_bind_journal(root,identity,ctx,rec,receipt,fd,event)
        assert "SECRET-CLOCK" not in "".join(traceback.format_exception(caught.type,caught.value,caught.tb))
        assert os.listdir(root)==[]
    finally:os.close(fd)

@pytest.mark.parametrize("excclass",[KeyboardInterrupt,SystemExit,type("KISub",(KeyboardInterrupt,),{}),type("SESub",(SystemExit,),{})])
def test_caller_deadline_controlflow_original_after_late_guard(excclass,valid_setup,monkeypatch):
    root,identity,ctx,rec,receipt,data,event=valid_setup
    fd=_deadline_pipe(data)
    clock=[100.0]
    monkeypatch.setattr(import_mod.time,"monotonic",lambda:clock[0])
    original=excclass("original-controlflow")
    def boom(*args,**kwargs):
        clock[0]=106.0
        raise original
    monkeypatch.setattr(import_mod,"stage_remote_cipher",boom)
    try:
        with pytest.raises(excclass) as caught:
            import_remote_cipher_and_bind_journal(root,identity,ctx,rec,receipt,fd,event,deadline=105.0)
        assert caught.value is original
    finally:os.close(fd)

def test_caller_deadline_late_actual_journal_keeps_prepared(valid_setup,monkeypatch):
    root,identity,ctx,rec,receipt,data,event=valid_setup
    fd=_deadline_pipe(data);clock=[100.0]
    monkeypatch.setattr(import_mod.time,"monotonic",lambda:clock[0])
    real=LocalJobJournal.prepare
    def late(self,*args,**kwargs):
        result=real(self,*args,**kwargs)
        clock[0]=105.0
        return result
    monkeypatch.setattr(LocalJobJournal,"prepare",late)
    try:
        with pytest.raises(RuntimeError,match="^Remote cipher import held$"):
            import_remote_cipher_and_bind_journal(root,identity,ctx,rec,receipt,fd,event,deadline=105.0)
        assert pathlib.Path(root,rec["artifact"]["leaf"]).read_bytes()==data
        assert LocalJobJournal(root).lookup(rec["job_id"],rec["request_digest"])["state"]=="prepared"
    finally:os.close(fd)

def test_stage_original_deadline_actual_wait(valid_setup):
    root,identity,ctx,rec,receipt,data,event=valid_setup
    readfd,writefd=os.pipe();os.set_blocking(readfd,False)
    start=time.monotonic()
    try:
        with pytest.raises(RuntimeError,match="^Remote cipher staging held$"):
            import_mod.stage_remote_cipher(root,identity,ctx,rec,receipt,readfd,event,deadline=start+0.1)
        assert 0.07 <= time.monotonic()-start < 1.0
        assert not pathlib.Path(root,rec["artifact"]["leaf"]).exists()
    finally:
        os.close(writefd);os.close(readfd)

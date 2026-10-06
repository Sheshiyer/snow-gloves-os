"""Linux-only test suite for runtime remote cipher stage contract."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import importlib.util
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

    target_file = os.path.join(scripts_path, "lib", "runtime_remote_cipher_stage.py")
    if not os.path.exists(target_file):
        target_file = os.path.join(repo_root, "runtime_remote_cipher_stage.py")
    spec = importlib.util.spec_from_file_location("lib.runtime_remote_cipher_stage", target_file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lib.runtime_remote_cipher_stage"] = mod
    spec.loader.exec_module(mod)
    return mod


stage_mod = _resolve_module()
stage_remote_cipher = stage_mod.stage_remote_cipher

from lib.runtime_operation_identity import checkpoint_digest


@pytest.fixture
def owned_root():
    temp_dir = tempfile.mkdtemp(prefix="sg-test-remote-stage-")
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
        "instanceId": "inst-001",
        "runtimeVersion": "3.8.50",
        "imageDigest": "a" * 64,
        "keyId": "key-sec-01",
    }
    job_id = "0123456789abcdef0123456789abcdef"
    request_digest = checkpoint_digest(context, job_id)
    test_bytes = b"ENC-CIPHER-DATA-1234567890"
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
        "object_version": "v-remote-1.0",
        "commit_key": f"{key_prefix}.commit.json",
        "commit_version": "v-commit-1.0",
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


def test_happy_path_staging(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        res = stage_remote_cipher(root_path, expected_id, context, record, receipt, r_fd, cancel_event)
    finally:
        os.close(r_fd)
        writer_thread.join()

    assert res["schema"] == "sg.local-cipher-stage.v1"
    assert res["state"] == "cipher-staged"
    assert res["replay_historical"] is False
    assert res["job_id"] == record["job_id"]
    assert res["request_digest"] == record["request_digest"]

    final_path = os.path.join(root_path, record["artifact"]["leaf"])
    assert os.path.exists(final_path)
    st = os.stat(final_path)
    assert (st.st_mode & 0o777) == 0o600
    assert st.st_nlink == 1
    with open(final_path, "rb") as f:
        assert f.read() == test_bytes

    # Check no leftover temp files
    names = os.listdir(root_path)
    assert names == [record["artifact"]["leaf"]]


def test_historical_replay_match(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    final_path = os.path.join(root_path, record["artifact"]["leaf"])
    with open(final_path, "wb") as f:
        f.write(test_bytes)
    os.chmod(final_path, 0o600)

    r_fd, w_fd = os.pipe()
    fl = fcntl.fcntl(r_fd, fcntl.F_GETFL)
    fcntl.fcntl(r_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    try:
        res = stage_remote_cipher(root_path, expected_id, context, record, receipt, r_fd, cancel_event)
    finally:
        os.close(r_fd)
        os.close(w_fd)

    assert res["replay_historical"] is True
    assert res["job_id"] == record["job_id"]


def test_invalid_request_digest_rejected_before_effects(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    record["request_digest"] = "f" * 64
    receipt["request_digest"] = "f" * 64
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        with pytest.raises(RuntimeError, match="Remote cipher staging held"):
            stage_remote_cipher(root_path, expected_id, context, record, receipt, r_fd, cancel_event)
    finally:
        os.close(r_fd)
        writer_thread.join()
    assert os.listdir(root_path) == []


def test_receipt_object_key_mismatch(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    receipt["object_key"] = "wrong/path.bin"
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        with pytest.raises(RuntimeError, match="Remote cipher staging held"):
            stage_remote_cipher(root_path, expected_id, context, record, receipt, r_fd, cancel_event)
    finally:
        os.close(r_fd)
        writer_thread.join()


def test_cancel_event_pre_set(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    cancel_event.set()
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes)
    try:
        with pytest.raises(RuntimeError, match="Remote cipher staging held"):
            stage_remote_cipher(root_path, expected_id, context, record, receipt, r_fd, cancel_event)
    finally:
        os.close(r_fd)
        writer_thread.join()


def test_short_eof_retains_partial_no_unlink(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, writer_thread = _make_pipe_with_writer(test_bytes[:5])
    try:
        with pytest.raises(RuntimeError, match="Remote cipher staging held"):
            stage_remote_cipher(root_path, expected_id, context, record, receipt, r_fd, cancel_event)
    finally:
        os.close(r_fd)
        writer_thread.join()

    files = os.listdir(root_path)
    assert len(files) == 1
    assert files[0].startswith(".sg-remote-stage-")
    assert files[0].endswith(".part")


def test_caller_fd_blocking_rejected(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    r_fd, w_fd = os.pipe()
    try:
        with pytest.raises(RuntimeError, match="Remote cipher staging held"):
            stage_remote_cipher(root_path, expected_id, context, record, receipt, r_fd, cancel_event)
    finally:
        os.close(r_fd)
        os.close(w_fd)


def test_regular_file_as_input_fd_rejected(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    temp_f = tempfile.NamedTemporaryFile()
    temp_f.write(test_bytes)
    temp_f.flush()
    fd = os.open(temp_f.name, os.O_RDONLY | os.O_NONBLOCK)
    try:
        with pytest.raises(RuntimeError, match="Remote cipher staging held"):
            stage_remote_cipher(root_path, expected_id, context, record, receipt, fd, cancel_event)
    finally:
        os.close(fd)
        temp_f.close()


def test_socketpair_source(valid_setup):
    root_path, expected_id, context, record, receipt, test_bytes, cancel_event = valid_setup
    s1, s2 = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    s1.setblocking(False)
    s2.setblocking(False)

    def _sock_writer():
        try:
            s2.sendall(test_bytes)
        finally:
            s2.close()

    t = threading.Thread(target=_sock_writer, daemon=True)
    t.start()
    try:
        res = stage_remote_cipher(root_path, expected_id, context, record, receipt, s1.fileno(), cancel_event)
        assert res["replay_historical"] is False
    finally:
        s1.close()
        t.join()


def test_actual_accepted_remote_receipt_contract(valid_setup):
    root, identity, ctx, record, _, data, event = valid_setup
    key = f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/{record['job_id']}/{record['request_digest']}/{record['artifact']['sha256']}"
    receipt = {
        'schema': 'sg.remote-checkpoint.v1',
        'state': 'remote-committed',
        'context': dict(ctx),
        'job_id': record['job_id'],
        'request_digest': record['request_digest'],
        'artifact': dict(record['artifact']),
        'object_key': key + '.bin',
        'object_version': 'owned-object',
        'commit_key': key + '.commit.json',
        'commit_version': 'owned-commit',
    }
    r, w = os.pipe()
    os.set_blocking(r, False)
    try:
        stage_mod._validate_inputs(root, identity, ctx, record, receipt, r, event, time.monotonic() + 15)
    finally:
        os.close(r)
        os.close(w)


def test_malformed_receipt_digest_is_redacted(valid_setup):
    root, identity, ctx, record, receipt, data, event = valid_setup
    receipt = dict(receipt)
    receipt['request_digest'] = []
    r, w = os.pipe()
    os.set_blocking(r, False)
    try:
        with pytest.raises(RuntimeError, match='^Remote cipher staging held$'):
            stage_remote_cipher(root, identity, ctx, record, receipt, r, event)
    finally:
        os.close(r)
        os.close(w)

def test_invalid_event_redacted(valid_setup):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,writer=_make_pipe_with_writer(data)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,None)
 finally:os.close(r);writer.join(1)

def test_receipt_bool_bytes_rejected_before_effects(valid_setup):
 root,identity,ctx,record,receipt,data,event=valid_setup
 import copy
 record=copy.deepcopy(record);receipt=copy.deepcopy(receipt);data=b'x';record['artifact']['bytes']=1;record['artifact']['sha256']=hashlib.sha256(data).hexdigest();receipt['artifact']=dict(record['artifact']);receipt['artifact']['bytes']=True
 key=f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/{record['job_id']}/{record['request_digest']}/{record['artifact']['sha256']}";receipt['object_key']=key+'.bin';receipt['commit_key']=key+'.commit.json'
 r,writer=_make_pipe_with_writer(data)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert os.listdir(root)==[]
 finally:os.close(r);writer.join(1)

def test_dup_close_failure_cannot_ack(valid_setup,monkeypatch):
 root,identity,ctx,record,receipt,data,event=valid_setup
 import stat
 r,writer=_make_pipe_with_writer(data);close=os.close;leaked=[]
 def fault(fd):
  st=os.fstat(fd);flags=fcntl.fcntl(fd,fcntl.F_GETFL)
  if fd!=r and stat.S_ISFIFO(st.st_mode) and flags&os.O_ACCMODE==os.O_RDONLY and not leaked:
   leaked.append(fd);raise OSError('OWNED-CLOSE-FAULT')
  return close(fd)
 monkeypatch.setattr(stage_mod.os,'close',fault)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
 finally:
  monkeypatch.setattr(stage_mod.os,'close',close)
  for fd in leaked:close(fd)
  close(r);writer.join(1)

def test_root_change_during_readiness_prevents_further_write(valid_setup,monkeypatch):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,writer=_make_pipe_with_writer(data);select_original=stage_mod.select.select;changed=[];moved=root+'-moved'
 def change(*args):
  result=select_original(*args)
  if result[0] and not changed:
   os.rename(root,moved);os.mkdir(root,0o700);changed.append(True)
  return result
 monkeypatch.setattr(stage_mod.select,'select',change)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert changed
  assert all(os.stat(os.path.join(moved,n)).st_size==0 for n in os.listdir(moved))
 finally:
  os.close(r);writer.join(1)
  import shutil
  shutil.rmtree(moved,ignore_errors=True)

def test_write_only_input_rejected_before_effects(valid_setup):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,w=os.pipe();os.set_blocking(w,False)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,w,event)
  assert os.listdir(root)==[]
 finally:os.close(r);os.close(w)

def test_nonblock_change_observed_before_read_holds(valid_setup,monkeypatch):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,writer=_make_pipe_with_writer(data);original=stage_mod.select.select;changed=[]
 def change(*args):
  result=original(*args)
  if result[0] and not changed:os.set_blocking(r,True);changed.append(True)
  return result
 monkeypatch.setattr(stage_mod.select,'select',change)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert changed
 finally:os.close(r);writer.join(1)

def test_replaced_temp_during_readiness_prevents_write(valid_setup,monkeypatch):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,writer=_make_pipe_with_writer(data);select_original=stage_mod.select.select;write_original=stage_mod.os.write;changed=[];writes=[]
 def change(*args):
  result=select_original(*args)
  if result[0] and not changed:
   name=next(n for n in os.listdir(root) if n.endswith('.part'));path=os.path.join(root,name);os.unlink(path)
   fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);changed.append(True)
  return result
 def observe(fd,b):
  if changed:writes.append(len(b))
  return write_original(fd,b)
 monkeypatch.setattr(stage_mod.select,'select',change);monkeypatch.setattr(stage_mod.os,'write',observe)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert changed and writes==[]
 finally:os.close(r);writer.join(1)

@pytest.mark.parametrize('kind',['temp','directory'])
def test_fsync_fault_holds_and_preserves_unknown(valid_setup,monkeypatch,kind):
 root,identity,ctx,record,receipt,data,event=valid_setup
 import stat
 r,writer=_make_pipe_with_writer(data);original=stage_mod.os.fsync
 def fail(fd):
  is_dir=stat.S_ISDIR(os.fstat(fd).st_mode)
  if is_dir==(kind=='directory'):raise OSError('OWNED-FSYNC-FAULT')
  return original(fd)
 monkeypatch.setattr(stage_mod.os,'fsync',fail)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert os.path.exists(os.path.join(root,record['artifact']['leaf']))==(kind=='directory')
  fd=os.open(root,os.O_DIRECTORY);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);os.close(fd)
 finally:os.close(r);writer.join(1)

def test_link_collision_does_not_overwrite(valid_setup,monkeypatch):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,writer=_make_pipe_with_writer(data);original=stage_mod.os.link;final=os.path.join(root,record['artifact']['leaf']);foreign=b'owned-foreign-collision'
 def collision(*args,**kwargs):
  fd=os.open(final,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(fd,foreign);os.close(fd)
  return original(*args,**kwargs)
 monkeypatch.setattr(stage_mod.os,'link',collision)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert pathlib.Path(final).read_bytes()==foreign
 finally:os.close(r);writer.join(1)

def test_same_bytes_final_replacement_is_held(valid_setup,monkeypatch):
 root,identity,ctx,record,receipt,data,event=valid_setup
 import stat
 r,writer=_make_pipe_with_writer(data);original=stage_mod.os.fsync;changed=[];final=os.path.join(root,record['artifact']['leaf'])
 def change(fd):
  result=original(fd)
  if stat.S_ISDIR(os.fstat(fd).st_mode) and not changed:
   os.unlink(final);f=os.open(final,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(f,data);os.close(f);changed.append(True)
  return result
 monkeypatch.setattr(stage_mod.os,'fsync',change)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert changed and pathlib.Path(final).read_bytes()==data
 finally:os.close(r);writer.join(1)

@pytest.mark.parametrize('mode',['trailing','digest'])
def test_invalid_body_has_no_final_publication(valid_setup,mode):
 root,identity,ctx,record,receipt,data,event=valid_setup
 if mode=='trailing':data+=b'x'
 else:data=b'x'*len(data)
 r,writer=_make_pipe_with_writer(data)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert not os.path.exists(os.path.join(root,record['artifact']['leaf']))
  assert all(os.stat(os.path.join(root,n)).st_size<=record['artifact']['bytes'] for n in os.listdir(root))
 finally:os.close(r);writer.join(1)

@pytest.mark.parametrize('mode',['cancel','clock'])
def test_cleanup_observer_prevents_ack(valid_setup,monkeypatch,mode):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,writer=_make_pipe_with_writer(data);open_original=stage_mod.os.open;close_original=stage_mod.os.close;clock_original=stage_mod.time.monotonic;target=[];observed=[]
 def capture(path,flags,*args,**kwargs):
  fd=open_original(path,flags,*args,**kwargs)
  if path==root and not target:target.append(fd)
  return fd
 def close(fd):
  result=close_original(fd)
  if target and fd==target[0]:
   observed.append(True)
   if mode=='cancel':event.set()
  return result
 monkeypatch.setattr(stage_mod.os,'open',capture);monkeypatch.setattr(stage_mod.os,'close',close);monkeypatch.setattr(stage_mod.time,'monotonic',lambda:clock_original()+(20 if mode=='clock' and observed else 0))
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert observed
 finally:os.close(r);writer.join(1)

def test_stalled_nonblocking_input_deadline_is_held(valid_setup,monkeypatch):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,w=os.pipe();os.set_blocking(r,False);clock_original=stage_mod.time.monotonic;elapsed=[]
 monkeypatch.setattr(stage_mod.time,'monotonic',lambda:clock_original()+(20 if elapsed else 0))
 def deadline(*a):elapsed.append(True);return [],[],[]
 monkeypatch.setattr(stage_mod.select,'select',deadline)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert elapsed
 finally:os.close(r);os.close(w)

def test_ordinary_hold_releases_descriptors_and_root_lock(valid_setup):
 root,identity,ctx,record,receipt,data,event=valid_setup
 r,writer=_make_pipe_with_writer(b'x'*len(data));writer.join(1);before=len(os.listdir('/proc/self/fd'));flags=fcntl.fcntl(r,fcntl.F_GETFL)
 try:
  with pytest.raises(RuntimeError,match='^Remote cipher staging held$'):stage_remote_cipher(root,identity,ctx,record,receipt,r,event)
  assert len(os.listdir('/proc/self/fd'))==before and fcntl.fcntl(r,fcntl.F_GETFL)==flags
  fd=os.open(root,os.O_DIRECTORY);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);os.close(fd)
 finally:os.close(r)

"""Tests for pure remote cipher metadata validation."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
import pathlib
import sys
import threading
import time

import pytest

try:
    from lib.runtime_operation_identity import checkpoint_digest
except ImportError:
    checkpoint_digest = None  # resolved in _resolve_paths


def _resolve_paths():
    repo_root = os.environ.get("SG_TEST_REPO_ROOT")
    if not repo_root:
        repo_root = str(pathlib.Path(__file__).resolve().parents[1])
    scripts_path = os.path.join(repo_root, "scripts")
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root, scripts_path


_repo_root, _scripts_path = _resolve_paths()

from lib.runtime_operation_identity import checkpoint_digest  # noqa: E402
from lib.runtime_remote_cipher_metadata import validate_remote_cipher_metadata  # noqa: E402

_MAX_BYTES = 64 * 1024 * 1024 + 4136
_HELD = "^Remote cipher metadata held$"


def _valid_bundle(test_bytes: bytes | None = None):
    if test_bytes is None:
        test_bytes = b"ENC-CIPHER-DATA-1234567890"
    context = {
        "instanceId": "inst-001",
        "runtimeVersion": "3.8.50",
        "imageDigest": "a" * 64,
        "keyId": "key-sec-01",
    }
    job_id = "0123456789abcdef0123456789abcdef"
    request_digest = checkpoint_digest(context, job_id)
    sha = hashlib.sha256(test_bytes).hexdigest()
    artifact = {
        "leaf": f"sg-encrypted-{job_id}.bin",
        "bytes": len(test_bytes),
        "sha256": sha,
    }
    record = {
        "schema": "sg.local-job.v1",
        "job_id": job_id,
        "request_digest": request_digest,
        "state": "artifact-verified",
        "artifact": dict(artifact),
    }
    prefix = (
        f"cp/v1/{context['instanceId']}/{context['imageDigest']}/"
        f"{job_id}/{request_digest}/{sha}"
    )
    receipt = {
        "schema": "sg.remote-checkpoint.v1",
        "state": "remote-committed",
        "context": dict(context),
        "job_id": job_id,
        "request_digest": request_digest,
        "artifact": dict(artifact),
        "object_key": prefix + ".bin",
        "object_version": "v-remote-1.0",
        "commit_key": prefix + ".commit.json",
        "commit_version": "v-commit-1.0",
    }
    return context, record, receipt


def test_valid_exact_fixture():
    ctx, rec, rcpt = _valid_bundle()
    out_ctx, out_rec, out_rcpt = validate_remote_cipher_metadata(ctx, rec, rcpt)
    assert out_ctx == ctx
    assert out_rec["schema"] == "sg.local-job.v1"
    assert out_rcpt["schema"] == "sg.remote-checkpoint.v1"
    assert out_rcpt["object_key"].endswith(".bin")
    assert out_rcpt["commit_key"].endswith(".commit.json")


def test_outputs_independent_copies_no_input_mutation():
    ctx, rec, rcpt = _valid_bundle()
    ctx_alias = ctx
    rec_art = rec["artifact"]
    rcpt_ctx = rcpt["context"]
    rcpt_art = rcpt["artifact"]
    snap = (
        copy.deepcopy(ctx),
        copy.deepcopy(rec),
        copy.deepcopy(rcpt),
    )
    o_ctx, o_rec, o_rcpt = validate_remote_cipher_metadata(ctx, rec, rcpt)
    assert (ctx, rec, rcpt) == snap
    assert o_ctx is not ctx and o_rec is not rec and o_rcpt is not rcpt
    assert o_ctx is not rcpt_ctx and o_rec["artifact"] is not rec_art
    assert o_rcpt["context"] is not rcpt_ctx and o_rcpt["artifact"] is not rcpt_art
    o_ctx["instanceId"] = "mutated"
    o_rec["job_id"] = "f" * 32
    o_rcpt["object_version"] = "mut"
    assert ctx_alias["instanceId"] == snap[0]["instanceId"]
    assert rec_art["bytes"] == snap[1]["artifact"]["bytes"]


def test_redacted_exception_no_cause():
    ctx, rec, rcpt = _valid_bundle()
    rcpt = copy.deepcopy(rcpt)
    rcpt["request_digest"] = []
    with pytest.raises(RuntimeError, match=_HELD) as ei:
        validate_remote_cipher_metadata(ctx, rec, rcpt)
    assert ei.value.__cause__ is None
    assert ei.value.args == ("Remote cipher metadata held",)


def test_checkpoint_digest_failure_redacted():
    ctx, rec, rcpt = _valid_bundle()
    rec = copy.deepcopy(rec)
    rec["request_digest"] = "b" * 64
    rcpt = copy.deepcopy(rcpt)
    rcpt["request_digest"] = "b" * 64
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_max_artifact_bytes_boundary():
    ctx, rec, rcpt = _valid_bundle(test_bytes=b"x")
    rec = copy.deepcopy(rec)
    rcpt = copy.deepcopy(rcpt)
    rec["artifact"]["bytes"] = _MAX_BYTES
    rcpt["artifact"]["bytes"] = _MAX_BYTES
    assert validate_remote_cipher_metadata(ctx, rec, rcpt)[1]["artifact"]["bytes"] == _MAX_BYTES
    rec["artifact"]["bytes"] = _MAX_BYTES + 1
    rcpt["artifact"]["bytes"] = _MAX_BYTES + 1
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)
    rec["artifact"]["bytes"] = 1
    rcpt["artifact"]["bytes"] = 1
    validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_zero_byte_artifact_rejected_not_truthy_equality():
    ctx, rec, rcpt = _valid_bundle(test_bytes=b"")
    rec = copy.deepcopy(rec)
    rcpt = copy.deepcopy(rcpt)
    rec["artifact"]["bytes"] = 0
    rec["artifact"]["sha256"] = hashlib.sha256(b"").hexdigest()
    rcpt["artifact"] = copy.deepcopy(rec["artifact"])
    prefix = (
        f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/"
        f"{rec['job_id']}/{rec['request_digest']}/{rec['artifact']['sha256']}"
    )
    rcpt["object_key"] = prefix + ".bin"
    rcpt["commit_key"] = prefix + ".commit.json"
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_receipt_artifact_bool_bytes_rejected():
    ctx, rec, rcpt = _valid_bundle(test_bytes=b"x")
    rec = copy.deepcopy(rec)
    rcpt = copy.deepcopy(rcpt)
    rcpt["artifact"] = dict(rec["artifact"])
    rcpt["artifact"]["bytes"] = False
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_record_artifact_bool_bytes_rejected():
    ctx, rec, rcpt = _valid_bundle(test_bytes=b"x")
    rec = copy.deepcopy(rec)
    rec["artifact"] = dict(rec["artifact"])
    rec["artifact"]["bytes"] = False
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_receipt_context_truthy_int_rejected():
    ctx, rec, rcpt = _valid_bundle()
    rcpt = copy.deepcopy(rcpt)
    bad = dict(rcpt["context"])
    bad["runtimeVersion"] = 1
    rcpt["context"] = bad
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_top_context_truthy_int_rejected():
    ctx, rec, rcpt = _valid_bundle()
    ctx = copy.deepcopy(ctx)
    ctx["runtimeVersion"] = 1
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_dict_subclass_rejected():
    class SubDict(dict):
        pass

    ctx, rec, rcpt = _valid_bundle()
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(SubDict(ctx), rec, rcpt)
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, SubDict(rec), rcpt)
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, SubDict(rcpt))


def test_unexpected_context_key_rejected():
    ctx, rec, rcpt = _valid_bundle()
    ctx = copy.deepcopy(ctx)
    ctx["extra"] = "x"
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_equal_object_and_commit_version_rejected():
    ctx, rec, rcpt = _valid_bundle()
    rcpt = copy.deepcopy(rcpt)
    rcpt["commit_version"] = rcpt["object_version"]
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_stage_metadata_parity_linux():
    # Only this private reference validator is pure; this is no root/FD proof.
    stage_path = os.path.join(_scripts_path, "lib", "runtime_remote_cipher_stage.py")
    spec = importlib.util.spec_from_file_location("lib.runtime_remote_cipher_stage", stage_path)
    stage_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage_mod)

    import tempfile

    temp_dir = tempfile.mkdtemp(prefix="sg-meta-parity-")
    root = os.path.realpath(temp_dir)
    os.chmod(root, 0o700)
    st = os.stat(root)
    identity = (st.st_dev, st.st_ino, os.geteuid(), 0o700)
    ctx, rec, rcpt = _valid_bundle()
    cancel = threading.Event()
    import os as _os

    r_fd, w_fd = _os.pipe()
    try:
        _os.set_blocking(r_fd, False)
        stage_ctx, stage_rec, stage_rcpt, *_ = stage_mod._validate_inputs(
            root,
            identity,
            ctx,
            rec,
            rcpt,
            r_fd,
            cancel,
            time.monotonic() + 15.0,
        )
    finally:
        _os.close(r_fd)
        _os.close(w_fd)
        try:
            _os.rmdir(root)
        except OSError:
            pass

    meta_ctx, meta_rec, meta_rcpt = validate_remote_cipher_metadata(ctx, rec, rcpt)
    assert meta_ctx == stage_ctx
    assert meta_rec == stage_rec
    assert meta_rcpt == stage_rcpt


def _mutate_bundle(ctx, rec, rcpt, field_path, value):
    c = copy.deepcopy(ctx)
    r = copy.deepcopy(rec)
    p = copy.deepcopy(rcpt)
    target = {"context": c, "record": r, "receipt": p}
    parts = field_path.split(".")
    obj = target[parts[0]]
    for part in parts[1:-1]:
        obj = obj[part]
    obj[parts[-1]] = value
    return c, r, p


@pytest.mark.parametrize(
    "field_path,value",
    [
        ("context.runtimeVersion", "3.8.51"),
        ("context.instanceId", "INVALID"),
        ("context.imageDigest", "g" * 64),
        ("context.keyId", ""),
        ("record.schema", "sg.local-job.v0"),
        ("record.state", "pending"),
        ("record.job_id", "not-hex"),
        ("record.request_digest", "c" * 64),
        ("record.artifact.leaf", "wrong.bin"),
        ("record.artifact.bytes", 0),
        ("record.artifact.sha256", "z" * 64),
        ("receipt.schema", "sg.remote-checkpoint.v0"),
        ("receipt.state", "remote-pending"),
        ("receipt.job_id", "ffffffffffffffffffffffffffffffff"),
        ("receipt.request_digest", "d" * 64),
        ("receipt.object_key", "cp/v1/x"),
        ("receipt.commit_key", "cp/v1/y"),
        ("receipt.object_version", ""),
        ("receipt.commit_version", "\x00bad"),
        ("receipt.context.runtimeVersion", "9.9.9"),
        ("receipt.artifact.bytes", True),
        ("record.artifact.bytes", True),
        ("receipt.context.keyId", 1),
        ("context.imageDigest", ["a"] * 64),
    ],
)
def test_rejection_matrix(field_path, value):
    ctx, rec, rcpt = _valid_bundle(test_bytes=b"matrix-payload")
    ctx, rec, rcpt = _mutate_bundle(ctx, rec, rcpt, field_path, value)
    if field_path.startswith("record.artifact."):
        sha = rec["artifact"]["sha256"]
        prefix = (
            f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/"
            f"{rec['job_id']}/{rec['request_digest']}/{sha}"
        )
        rcpt["object_key"] = prefix + ".bin"
        rcpt["commit_key"] = prefix + ".commit.json"
        if field_path == "receipt.artifact.bytes" and value is True:
            rcpt["artifact"] = dict(rec["artifact"])
            rcpt["artifact"]["bytes"] = True
    with pytest.raises(RuntimeError, match=_HELD):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


def test_keyboard_interrupt_propagates(monkeypatch):
    ctx, rec, rcpt = _valid_bundle()

    def _boom(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "lib.runtime_remote_cipher_metadata.checkpoint_digest",
        _boom,
    )
    with pytest.raises(KeyboardInterrupt):
        validate_remote_cipher_metadata(ctx, rec, rcpt)


# Independent adversarial type, identity, parity and diagnostic-chain checks.
import copy, os, threading, time, traceback
import pytest
from lib import runtime_remote_cipher_metadata as module
from lib.runtime_remote_cipher_stage import _validate_inputs

class DictSubclass(dict):pass
class StringSubclass(str):pass
class IntegerSubclass(int):pass

@pytest.mark.parametrize('path,value',[
 ('context.instanceId',StringSubclass('inst-001')),
 ('record.artifact.bytes',IntegerSubclass(24)),
 ('receipt.artifact.bytes',IntegerSubclass(24)),
 ('receipt.object_version',StringSubclass('v-remote-1.0')),
 ('record.artifact.bytes',1.0),('receipt.artifact.bytes',1.0),
 ('record.artifact.bytes',True),('receipt.artifact.bytes',True),
 ('record.artifact.bytes',False),('receipt.artifact.bytes',False),
 ('record.artifact.bytes',float('nan')),('receipt.artifact.bytes',float('nan')),
 ('record.artifact.bytes',None),('receipt.context',DictSubclass()),
 ('record.artifact',DictSubclass()),('receipt.artifact',DictSubclass()),
 ('receipt.object_version','x'*257),('receipt.object_version','x y'),
 ('receipt.object_version','x\n'),('receipt.object_version','x\x7f'),
 ('receipt.object_version','é'),('receipt.object_version',b'v-remote-1.0'),
 ('receipt.commit_version',1),('receipt.artifact.sha256',StringSubclass('a'*64)),
 ('context.instanceId','inst-001\n'),('context.instanceId','x'*65),
 ('context.keyId','key-sec-01\n'),('record.job_id','a'*32+'\n'),
 ('record.request_digest','a'*64+'\n'),('record.artifact.sha256','a'*64+'\n'),
])
def test_strict_type_and_limits(path,value):
 bundle=_mutate_bundle(*_valid_bundle(),path,value)
 with pytest.raises(RuntimeError,match='^Remote cipher metadata held$'):
  module.validate_remote_cipher_metadata(*bundle)

@pytest.mark.parametrize('location',['context','record','receipt','record.artifact','receipt.artifact','receipt.context'])
def test_plain_keys_and_exact_cardinality(location):
 for mode in ['key_subclass','extra','missing']:
  bundle=_valid_bundle();maps=dict(zip(['context','record','receipt'],bundle));parts=location.split('.');target=maps[parts[0]]
  for part in parts[1:]:target=target[part]
  key=next(iter(target));value=target.pop(key)
  if mode=='key_subclass':target[StringSubclass(key)]=value
  elif mode=='extra':target[key]=value;target['unexpected']=None
  with pytest.raises(RuntimeError,match='^Remote cipher metadata held$'):module.validate_remote_cipher_metadata(*bundle)

def test_aliases_are_separated_both_directions():
 ctx,rec,receipt=_valid_bundle();receipt['context']=ctx;receipt['artifact']=rec['artifact']
 outputs=module.validate_remote_cipher_metadata(ctx,rec,receipt);snapshot=copy.deepcopy(outputs)
 ctx['instanceId']='changed';rec['artifact']['bytes']=3
 assert outputs==snapshot
 outputs[0]['keyId']='changed';outputs[1]['artifact']['bytes']=4
 assert outputs[2]['context']['keyId']=='key-sec-01'
 assert outputs[2]['artifact']['bytes']==snapshot[1]['artifact']['bytes']

@pytest.mark.parametrize('failure',[ValueError('diagnostic-marker'),RuntimeError('diagnostic-marker'),KeyboardInterrupt(),SystemExit(7)])
def test_exception_redaction_and_control_flow(monkeypatch,failure):
 def raise_failure(*args):raise failure
 monkeypatch.setattr(module,'checkpoint_digest',raise_failure)
 if isinstance(failure,(KeyboardInterrupt,SystemExit)):
  with pytest.raises(type(failure)):module.validate_remote_cipher_metadata(*_valid_bundle())
 else:
  with pytest.raises(RuntimeError,match='^Remote cipher metadata held$') as caught:module.validate_remote_cipher_metadata(*_valid_bundle())
  assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True
  assert 'diagnostic-marker' not in ''.join(traceback.format_exception(caught.value))

@pytest.mark.parametrize('count',[1,67113000])
def test_pure_reference_parity_without_root_or_fd_effects(count):
 bundle=_valid_bundle();bundle[1]['artifact']['bytes']=count;bundle[2]['artifact']['bytes']=count
 reference=_validate_inputs('/not-opened-reference',(1,1,os.geteuid(),0o700),*bundle,12345,threading.Event(),time.monotonic()+15)
 assert module.validate_remote_cipher_metadata(*bundle)==reference[:3]

def test_printable_version_boundaries_are_opaque_syntax():
 bundle=_valid_bundle();bundle[2]['object_version']='!'*256;bundle[2]['commit_version']='~'*256
 assert module.validate_remote_cipher_metadata(*bundle)[2]['object_version']=='!'*256

def test_forged_same_message_dependency_chain_is_redacted(monkeypatch):
 bundle=_valid_bundle()
 def dependency_failure(*args):
  try:raise ValueError('diagnostic-marker')
  except ValueError:raise RuntimeError('Remote cipher metadata held')
 monkeypatch.setattr(module.copy,'deepcopy',dependency_failure)
 with pytest.raises(RuntimeError,match='^Remote cipher metadata held$') as caught:
  module.validate_remote_cipher_metadata(*bundle)
 assert caught.value.__suppress_context__ is True
 assert 'diagnostic-marker' not in ''.join(traceback.format_exception(caught.value))

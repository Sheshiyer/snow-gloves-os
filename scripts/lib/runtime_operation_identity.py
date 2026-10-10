import hashlib
import hmac
import json
import re

_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[a-z0-9-]{1,64}")
_MAX_BYTES = 64 * 1024 * 1024 + 4136


def _fail():
    raise ValueError("Operation identity held") from None


def _val_exact_dict(d, keys):
    if type(d) is not dict or any(type(k) is not str for k in d) or set(d.keys()) != keys:
        _fail()


def _val_context(ctx):
    _val_exact_dict(ctx, {"instanceId", "runtimeVersion", "imageDigest", "keyId"})
    if type(ctx["instanceId"]) is not str or not _ID_RE.fullmatch(ctx["instanceId"]):
        _fail()
    if type(ctx["runtimeVersion"]) is not str or ctx["runtimeVersion"] != "3.8.50":
        _fail()
    if type(ctx["imageDigest"]) is not str or not _HEX64.fullmatch(ctx["imageDigest"]):
        _fail()
    if type(ctx["keyId"]) is not str or not _ID_RE.fullmatch(ctx["keyId"]):
        _fail()
    return {
        "instanceId": ctx["instanceId"],
        "runtimeVersion": ctx["runtimeVersion"],
        "imageDigest": ctx["imageDigest"],
        "keyId": ctx["keyId"],
    }


def _val_hex(val, pattern):
    if type(val) is not str or not pattern.fullmatch(val):
        _fail()


def _val_artifact(art, exp_job_id=None):
    _val_exact_dict(art, {"leaf", "bytes", "sha256"})
    leaf, b_count, s256 = art["leaf"], art["bytes"], art["sha256"]
    if type(leaf) is not str or not leaf.startswith("sg-encrypted-") or not leaf.endswith(".bin"):
        _fail()
    leaf_hex = leaf[13:-4]
    _val_hex(leaf_hex, _HEX32)
    if exp_job_id is not None and leaf_hex != exp_job_id:
        _fail()
    if type(b_count) is not int or type(b_count) is bool or not (1 <= b_count <= _MAX_BYTES):
        _fail()
    _val_hex(s256, _HEX64)
    return {"leaf": leaf, "bytes": b_count, "sha256": s256}


def _compute_digest(op, ctx_copy, req_dict):
    obj = {
        "context": ctx_copy,
        "operation": op,
        "request": req_dict,
        "schema": "sg.operation-request.v1",
    }
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def checkpoint_digest(context, job_id):
    ctx = _val_context(context)
    _val_hex(job_id, _HEX32)
    return _compute_digest("checkpoint", ctx, {"job_id": job_id})


def restore_digest(context, restore_job_id, source_checkpoint_job_id, source_request_digest, artifact):
    ctx = _val_context(context)
    _val_hex(restore_job_id, _HEX32)
    _val_hex(source_checkpoint_job_id, _HEX32)
    if restore_job_id == source_checkpoint_job_id:
        _fail()
    _val_hex(source_request_digest, _HEX64)
    art = _val_artifact(artifact, source_checkpoint_job_id)
    req = {
        "bytes": art["bytes"],
        "leaf": art["leaf"],
        "restore_job_id": restore_job_id,
        "sha256": art["sha256"],
        "source_checkpoint_job_id": source_checkpoint_job_id,
        "source_request_digest": source_request_digest,
    }
    return _compute_digest("restore", ctx, req)


def validate_checkpoint(context, payload):
    ctx = _val_context(context)
    _val_exact_dict(payload, {"job_id", "request_digest"})
    job_id = payload["job_id"]
    req_digest = payload["request_digest"]
    _val_hex(job_id, _HEX32)
    _val_hex(req_digest, _HEX64)
    expected = checkpoint_digest(ctx, job_id)
    if not hmac.compare_digest(req_digest, expected):
        _fail()
    return {"job_id": job_id, "request_digest": req_digest}


def validate_restore(context, payload):
    ctx = _val_context(context)
    _val_exact_dict(payload, {
        "restore_job_id", "request_digest", "source_checkpoint_job_id",
        "source_request_digest", "leaf", "bytes", "sha256"
    })
    r_id = payload["restore_job_id"]
    req_dig = payload["request_digest"]
    s_id = payload["source_checkpoint_job_id"]
    s_dig = payload["source_request_digest"]
    _val_hex(r_id, _HEX32)
    _val_hex(req_dig, _HEX64)
    _val_hex(s_id, _HEX32)
    if r_id == s_id:
        _fail()
    _val_hex(s_dig, _HEX64)
    art = _val_artifact({"leaf": payload["leaf"], "bytes": payload["bytes"], "sha256": payload["sha256"]}, s_id)
    expected = restore_digest(ctx, r_id, s_id, s_dig, art)
    if not hmac.compare_digest(req_dig, expected):
        _fail()
    return {
        "bytes": art["bytes"],
        "leaf": art["leaf"],
        "request_digest": req_dig,
        "restore_job_id": r_id,
        "sha256": art["sha256"],
        "source_checkpoint_job_id": s_id,
        "source_request_digest": s_dig,
    }

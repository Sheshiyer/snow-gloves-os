"""Pure remote cipher metadata validation (no filesystem or transport)."""
from __future__ import annotations

import copy
import hmac
import re
from typing import Any

try:
    from .runtime_operation_identity import checkpoint_digest
except ImportError:
    from lib.runtime_operation_identity import checkpoint_digest

_MAX_CIPHERTEXT_SIZE = 64 * 1024 * 1024 + 4136
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
_CONTEXT_KEYS = frozenset({"instanceId", "runtimeVersion", "imageDigest", "keyId"})
_RECORD_KEYS = frozenset({"schema", "job_id", "request_digest", "state", "artifact"})
_ARTIFACT_KEYS = frozenset({"leaf", "bytes", "sha256"})
_RECEIPT_KEYS = frozenset({
    "schema",
    "state",
    "context",
    "job_id",
    "request_digest",
    "artifact",
    "object_key",
    "object_version",
    "commit_key",
    "commit_version",
})


def _hold() -> None:
    raise RuntimeError("Remote cipher metadata held") from None


def _plain_dict_exact_keys(obj: Any, expected_keys: frozenset[str]) -> dict[str, Any]:
    if type(obj) is not dict:
        _hold()
    if len(obj) != len(expected_keys):
        _hold()
    for k in obj:
        if type(k) is not str:
            _hold()
    if set(obj.keys()) != expected_keys:
        _hold()
    return obj


def _validate_ascii_version(val: Any) -> str:
    if type(val) is not str or not (1 <= len(val) <= 256):
        _hold()
    for c in val:
        if ord(c) < 33 or ord(c) > 126:
            _hold()
    return val


def _validate_context_fields(context: dict[str, Any]) -> dict[str, str]:
    ctx = _plain_dict_exact_keys(context, _CONTEXT_KEYS)
    for v in ctx.values():
        if type(v) is not str:
            _hold()
    if ctx["runtimeVersion"] != "3.8.50":
        _hold()
    if len(ctx["instanceId"]) > 64 or not _ID_RE.fullmatch(ctx["instanceId"]):
        _hold()
    if len(ctx["keyId"]) > 64 or not _ID_RE.fullmatch(ctx["keyId"]):
        _hold()
    if len(ctx["imageDigest"]) != 64 or not _HEX64_RE.fullmatch(ctx["imageDigest"]):
        _hold()
    return {
        "instanceId": ctx["instanceId"],
        "runtimeVersion": ctx["runtimeVersion"],
        "imageDigest": ctx["imageDigest"],
        "keyId": ctx["keyId"],
    }


def _validate_artifact(job_id: str, art: Any) -> dict[str, Any]:
    artifact = _plain_dict_exact_keys(art, _ARTIFACT_KEYS)
    leaf = artifact["leaf"]
    b_count = artifact["bytes"]
    s256 = artifact["sha256"]
    if type(leaf) is not str or leaf != f"sg-encrypted-{job_id}.bin":
        _hold()
    if type(b_count) is not int or isinstance(b_count, bool):
        _hold()
    if not (1 <= b_count <= _MAX_CIPHERTEXT_SIZE):
        _hold()
    if type(s256) is not str or len(s256) != 64 or not _HEX64_RE.fullmatch(s256):
        _hold()
    return {"leaf": leaf, "bytes": b_count, "sha256": s256}


def validate_remote_cipher_metadata(
    context: dict[str, Any],
    record: dict[str, Any],
    receipt: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    try:
        validated_ctx = _validate_context_fields(context)

        rec = _plain_dict_exact_keys(record, _RECORD_KEYS)
        if type(rec["schema"]) is not str or rec["schema"] != "sg.local-job.v1":
            _hold()
        job_id = rec["job_id"]
        req_digest = rec["request_digest"]
        if type(job_id) is not str or len(job_id) != 32 or not _HEX32_RE.fullmatch(job_id):
            _hold()
        if type(req_digest) is not str or len(req_digest) != 64 or not _HEX64_RE.fullmatch(req_digest):
            _hold()
        if type(rec["state"]) is not str or rec["state"] != "artifact-verified":
            _hold()

        try:
            expected_req_digest = checkpoint_digest(validated_ctx, job_id)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if not hmac.compare_digest(req_digest, expected_req_digest):
            _hold()

        validated_art = _validate_artifact(job_id, rec["artifact"])
        validated_rec = {
            "schema": "sg.local-job.v1",
            "job_id": job_id,
            "request_digest": req_digest,
            "state": "artifact-verified",
            "artifact": copy.deepcopy(validated_art),
        }

        exp_prefix = (
            f"cp/v1/{validated_ctx['instanceId']}/{validated_ctx['imageDigest']}/"
            f"{job_id}/{req_digest}/{validated_art['sha256']}"
        )
        exp_obj_key = f"{exp_prefix}.bin"
        exp_commit_key = f"{exp_prefix}.commit.json"

        rcpt = _plain_dict_exact_keys(receipt, _RECEIPT_KEYS)
        for k in (
            "schema",
            "state",
            "job_id",
            "request_digest",
            "object_key",
            "object_version",
            "commit_key",
            "commit_version",
        ):
            if type(rcpt[k]) is not str:
                _hold()

        receipt_ctx = _validate_context_fields(rcpt["context"])
        if receipt_ctx != validated_ctx:
            _hold()

        receipt_art = _validate_artifact(job_id, rcpt["artifact"])
        if receipt_art != validated_art:
            _hold()

        if rcpt["schema"] != "sg.remote-checkpoint.v1" or rcpt["state"] != "remote-committed":
            _hold()
        if rcpt["job_id"] != job_id:
            _hold()
        if not hmac.compare_digest(rcpt["request_digest"], req_digest):
            _hold()
        if rcpt["object_key"] != exp_obj_key or rcpt["commit_key"] != exp_commit_key:
            _hold()

        o_ver = _validate_ascii_version(rcpt["object_version"])
        c_ver = _validate_ascii_version(rcpt["commit_version"])
        if o_ver == c_ver:
            _hold()

        validated_receipt = {
            "schema": "sg.remote-checkpoint.v1",
            "state": "remote-committed",
            "context": copy.deepcopy(validated_ctx),
            "job_id": job_id,
            "request_digest": req_digest,
            "artifact": copy.deepcopy(validated_art),
            "object_key": exp_obj_key,
            "object_version": o_ver,
            "commit_key": exp_commit_key,
            "commit_version": c_ver,
        }

        out_ctx = copy.deepcopy(validated_ctx)
        out_rec = copy.deepcopy(validated_rec)
        out_rcpt = copy.deepcopy(validated_receipt)
        return out_ctx, out_rec, out_rcpt
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()

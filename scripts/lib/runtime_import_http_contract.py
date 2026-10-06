"""Pure import HTTP header/result contract (no transport or filesystem)."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

try:
    from .runtime_remote_cipher_metadata import validate_remote_cipher_metadata
except ImportError:
    from lib.runtime_remote_cipher_metadata import validate_remote_cipher_metadata

_HOLD_MSG = "Import HTTP contract held"
_CONTENT_TYPE = "application/vnd.sg.cipher-export+v1"
_METADATA_HEADER = "X-SG-Import-Metadata"
_MIN_CONTENT_LENGTH = 1
_MAX_CONTENT_LENGTH = 67113000
_METADATA_MAX_BYTES = 8192
_RESULT_KEYS = frozenset({
    "schema",
    "state",
    "context",
    "job_id",
    "request_digest",
    "artifact",
    "replay_stage",
    "replay_journal",
})
_CONTEXT_KEYS = frozenset({"instanceId", "runtimeVersion", "imageDigest", "keyId"})
_ARTIFACT_KEYS = frozenset({"leaf", "bytes", "sha256"})
_HEADER_TOKEN_RE = re.compile(r"^[!#$%&\'*+\-.^_`|~0-9A-Za-z]+$")
_CL_RE = re.compile(r"^(?:[1-9][0-9]{0,7}|67113000)$")


def _hold() -> None:
    raise RuntimeError(_HOLD_MSG) from None


def _ascii_header_name(name: str) -> None:
    if not name or not _HEADER_TOKEN_RE.fullmatch(name):
        _hold()
    for c in name:
        o = ord(c)
        if o < 33 or o > 126:
            _hold()


def _ascii_header_value(value: str) -> None:
    for c in value:
        o = ord(c)
        if o < 32 or o > 126:
            _hold()


def _forbidden_import_header(name: str) -> None:
    lower = name.lower()
    if lower == "transfer-encoding" or lower == "expect":
        _hold()


def _json_pairs_no_dup_local(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    out: dict[str, Any] = {}
    for key, val in pairs:
        if type(key) is not str:
            _hold()
        if key in seen:
            _hold()
        seen.add(key)
        out[key] = val
    return out


def _reject_nonascii_strings(obj: Any) -> None:
    if type(obj) is str:
        for c in obj:
            o = ord(c)
            if o < 32 or o > 126:
                _hold()
        return
    if type(obj) is dict:
        for k, v in obj.items():
            if type(k) is not str:
                _hold()
            _reject_nonascii_strings(k)
            _reject_nonascii_strings(v)
        return
    if type(obj) is list:
        for item in obj:
            _reject_nonascii_strings(item)
        return
    if type(obj) is int:
        return
    _hold()


def _metadata_outer_exact(obj: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if type(obj) is not dict:
        _hold()
    if set(obj.keys()) != {"context", "record", "remote_receipt"}:
        _hold()
    ctx = obj["context"]
    rec = obj["record"]
    rcpt = obj["remote_receipt"]
    if type(ctx) is not dict or type(rec) is not dict or type(rcpt) is not dict:
        _hold()
    return ctx, rec, rcpt


def _trusted_context_matches(validated: dict[str, str], trusted_context: Any) -> None:
    if type(trusted_context) is not dict:
        _hold()
    if len(trusted_context) != len(_CONTEXT_KEYS):
        _hold()
    for k in trusted_context:
        if type(k) is not str:
            _hold()
    if set(trusted_context.keys()) != _CONTEXT_KEYS:
        _hold()
    for k in _CONTEXT_KEYS:
        v = trusted_context[k]
        if type(v) is not str:
            _hold()
        if v != validated[k]:
            _hold()


def _parse_content_length(raw: str) -> int:
    if type(raw) is not str:
        _hold()
    if not _CL_RE.fullmatch(raw):
        _hold()
    value = int(raw, 10)
    if not (_MIN_CONTENT_LENGTH <= value <= _MAX_CONTENT_LENGTH):
        _hold()
    return value


def _detach_context(ctx: dict[str, str]) -> dict[str, str]:
    return {
        "instanceId": ctx["instanceId"],
        "runtimeVersion": ctx["runtimeVersion"],
        "imageDigest": ctx["imageDigest"],
        "keyId": ctx["keyId"],
    }


def _detach_artifact(art: dict[str, Any]) -> dict[str, Any]:
    b_count = art["bytes"]
    if type(b_count) is not int or type(b_count) is bool:
        _hold()
    return {
        "leaf": art["leaf"],
        "bytes": b_count,
        "sha256": art["sha256"],
    }


def _detach_record(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": rec["schema"],
        "job_id": rec["job_id"],
        "request_digest": rec["request_digest"],
        "state": rec["state"],
        "artifact": _detach_artifact(rec["artifact"]),
    }


def _detach_receipt(rcpt: dict[str, Any]) -> dict[str, Any]:
    ctx = rcpt["context"]
    if type(ctx) is not dict:
        _hold()
    return {
        "schema": rcpt["schema"],
        "state": rcpt["state"],
        "context": _detach_context(ctx),
        "job_id": rcpt["job_id"],
        "request_digest": rcpt["request_digest"],
        "artifact": _detach_artifact(rcpt["artifact"]),
        "object_key": rcpt["object_key"],
        "object_version": rcpt["object_version"],
        "commit_key": rcpt["commit_key"],
        "commit_version": rcpt["commit_version"],
    }


def parse_import_headers(
    header_pairs: list[tuple[str, str]],
    trusted_context: dict[str, str],
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    try:
        if type(header_pairs) is not list:
            _hold()
        seen_names: set[str] = set()
        content_type: str | None = None
        content_length: str | None = None
        metadata_raw: str | None = None

        for item in header_pairs:
            if type(item) is not tuple or len(item) != 2:
                _hold()
            name, value = item
            if type(name) is not str or type(value) is not str:
                _hold()
            _ascii_header_name(name)
            _ascii_header_value(value)
            _forbidden_import_header(name)
            norm = name.lower()
            if norm in seen_names:
                _hold()
            seen_names.add(norm)

            if norm == "content-type":
                content_type = value
            elif norm == "content-length":
                content_length = value
            elif norm == _METADATA_HEADER.lower():
                metadata_raw = value

        if content_type is None or content_length is None or metadata_raw is None:
            _hold()
        if content_type != _CONTENT_TYPE:
            _hold()

        meta_bytes = metadata_raw.encode("ascii", "strict")
        if len(meta_bytes) > _METADATA_MAX_BYTES:
            _hold()

        try:
            metadata_obj = json.loads(
                metadata_raw,
                object_pairs_hook=_json_pairs_no_dup_local,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _reject_nonascii_strings(metadata_obj)
        raw_ctx, raw_rec, raw_rcpt = _metadata_outer_exact(metadata_obj)

        validated_ctx, validated_rec, validated_rcpt = validate_remote_cipher_metadata(
            raw_ctx,
            raw_rec,
            raw_rcpt,
        )
        _trusted_context_matches(validated_ctx, trusted_context)

        cl_value = _parse_content_length(content_length)
        art_bytes = validated_rec["artifact"]["bytes"]
        if type(art_bytes) is not int or type(art_bytes) is bool:
            _hold()
        if cl_value != art_bytes:
            _hold()

        return (
            _detach_context(validated_ctx),
            _detach_record(validated_rec),
            _detach_receipt(validated_rcpt),
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()


def _validate_result_shape_before_compare(result: Any) -> dict[str, Any]:
    if type(result) is not dict:
        _hold()
    if len(result) != len(_RESULT_KEYS):
        _hold()
    for k in result:
        if type(k) is not str:
            _hold()
    if set(result.keys()) != _RESULT_KEYS:
        _hold()

    schema = result["schema"]
    state = result["state"]
    if type(schema) is not str or schema != "sg.local-cipher-import.v1":
        _hold()
    if type(state) is not str or state != "cipher-journal-bound":
        _hold()

    replay_stage = result["replay_stage"]
    replay_journal = result["replay_journal"]
    if type(replay_stage) is not bool:
        _hold()
    if type(replay_journal) is not bool:
        _hold()

    ctx = result["context"]
    if type(ctx) is not dict or len(ctx) != len(_CONTEXT_KEYS):
        _hold()
    for k in ctx:
        if type(k) is not str:
            _hold()
    if set(ctx.keys()) != _CONTEXT_KEYS:
        _hold()
    for k in _CONTEXT_KEYS:
        if type(ctx[k]) is not str:
            _hold()

    job_id = result["job_id"]
    req_digest = result["request_digest"]
    if type(job_id) is not str or type(req_digest) is not str:
        _hold()

    art = result["artifact"]
    if type(art) is not dict or len(art) != len(_ARTIFACT_KEYS):
        _hold()
    for k in art:
        if type(k) is not str:
            _hold()
    if set(art.keys()) != _ARTIFACT_KEYS:
        _hold()
    leaf = art["leaf"]
    b_count = art["bytes"]
    sha = art["sha256"]
    if type(leaf) is not str or type(sha) is not str:
        _hold()
    if type(b_count) is not int or type(b_count) is bool:
        _hold()

    return {
        "schema": schema,
        "state": state,
        "context": {
            "instanceId": ctx["instanceId"],
            "runtimeVersion": ctx["runtimeVersion"],
            "imageDigest": ctx["imageDigest"],
            "keyId": ctx["keyId"],
        },
        "job_id": job_id,
        "request_digest": req_digest,
        "artifact": {"leaf": leaf, "bytes": b_count, "sha256": sha},
        "replay_stage": replay_stage,
        "replay_journal": replay_journal,
    }


def validate_import_result(
    result: dict[str, Any],
    context: dict[str, str],
    record: dict[str, Any],
    remote_receipt: dict[str, Any],
) -> dict[str, Any]:
    try:
        validated_ctx, validated_rec, validated_rcpt = validate_remote_cipher_metadata(
            context,
            record,
            remote_receipt,
        )
        shaped = _validate_result_shape_before_compare(result)

        if shaped["context"] != validated_ctx:
            _hold()
        if shaped["job_id"] != validated_rec["job_id"]:
            _hold()
        if shaped["request_digest"] != validated_rec["request_digest"]:
            _hold()
        if shaped["artifact"] != validated_rec["artifact"]:
            _hold()

        out = {
            "schema": "sg.local-cipher-import.v1",
            "state": "cipher-journal-bound",
            "context": copy.deepcopy(validated_ctx),
            "job_id": validated_rec["job_id"],
            "request_digest": validated_rec["request_digest"],
            "artifact": copy.deepcopy(validated_rec["artifact"]),
            "replay_stage": shaped["replay_stage"],
            "replay_journal": shaped["replay_journal"],
        }
        if (
            out["context"] is validated_ctx
            or out["artifact"] is validated_rec["artifact"]
            or out["context"] is shaped["context"]
            or out["artifact"] is shaped["artifact"]
        ):
            _hold()
        return out
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib.runtime_import_http_contract import (  # noqa: E402
    parse_import_headers,
    validate_import_result,
)
from lib.runtime_operation_identity import checkpoint_digest  # noqa: E402

_HOLD = "Import HTTP contract held"
_CT = "application/vnd.sg.cipher-export+v1"


def _hex64(ch: str = "a") -> str:
    return ch * 64


def _valid_bundle(byte_count: int = 4096):
    job_id = "ab" * 16
    context = {
        "instanceId": "inst-1",
        "runtimeVersion": "3.8.50",
        "imageDigest": _hex64("c"),
        "keyId": "key-1",
    }
    request_digest = checkpoint_digest(context, job_id)
    artifact = {
        "leaf": f"sg-encrypted-{job_id}.bin",
        "bytes": byte_count,
        "sha256": _hex64("d"),
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
        f"{job_id}/{request_digest}/{artifact['sha256']}"
    )
    remote_receipt = {
        "schema": "sg.remote-checkpoint.v1",
        "state": "remote-committed",
        "context": dict(context),
        "job_id": job_id,
        "request_digest": request_digest,
        "artifact": dict(artifact),
        "object_key": f"{prefix}.bin",
        "object_version": "v-object-1",
        "commit_key": f"{prefix}.commit.json",
        "commit_version": "v-commit-2",
    }
    return context, record, remote_receipt, job_id, request_digest, artifact


def _metadata_json(context, record, remote_receipt) -> str:
    return json.dumps(
        {"context": context, "record": record, "remote_receipt": remote_receipt},
        separators=(",", ":"),
        sort_keys=True,
    )


def _headers(context, record, remote_receipt, extra=None):
    meta = _metadata_json(context, record, remote_receipt)
    pairs = [
        ("Host", "import.example"),
        ("Authorization", "Bearer test-token"),
        ("Content-Type", _CT),
        ("Content-Length", str(record["artifact"]["bytes"])),
        ("X-SG-Import-Metadata", meta),
    ]
    if extra:
        pairs.extend(extra)
    return pairs


def _import_result(context, record, replay_stage: bool, replay_journal: bool):
    return {
        "schema": "sg.local-cipher-import.v1",
        "state": "cipher-journal-bound",
        "context": dict(context),
        "job_id": record["job_id"],
        "request_digest": record["request_digest"],
        "artifact": dict(record["artifact"]),
        "replay_stage": replay_stage,
        "replay_journal": replay_journal,
    }


def test_parse_success_with_extra_headers():
    context, record, receipt, _, _, _ = _valid_bundle()
    parsed = parse_import_headers(_headers(context, record, receipt), context)
    assert parsed[0] == context
    assert parsed[1]["job_id"] == record["job_id"]
    assert parsed[2]["object_key"].endswith(".bin")


def test_parse_allows_same_key_name_in_different_metadata_objects():
    context, record, receipt, _, _, _ = _valid_bundle()
    # Different objects may reuse field names; only per-object duplicate keys are forbidden.
    meta = _metadata_json(context, record, receipt)
    assert "job_id" in meta
    parsed = parse_import_headers(_headers(context, record, receipt), context)
    assert parsed[1]["schema"] == "sg.local-job.v1"


def test_parse_rejects_per_object_duplicate_json_keys():
    context, record, receipt, _, _, _ = _valid_bundle()
    valid = _metadata_json(context, record, receipt)
    assert json.loads(valid)
    corrupted = valid.replace('"schema":"sg.local-job.v1"', '"schema":"sg.local-job.v1","schema":"sg.local-job.v1"', 1)
    assert json.loads(corrupted) == json.loads(valid)
    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "X-SG-Import-Metadata" else (p[0], corrupted) for p in pairs]
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)


def test_parse_rejects_duplicate_header_names_case_insensitive():
    context, record, receipt, _, _, _ = _valid_bundle()
    pairs = _headers(context, record, receipt)
    pairs.append(("content-type", "application/octet-stream"))
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)


def test_parse_rejects_transfer_encoding_and_expect():
    context, record, receipt, _, _, _ = _valid_bundle()
    for name in ("Transfer-Encoding", "Expect"):
        with pytest.raises(RuntimeError, match=_HOLD):
            parse_import_headers(_headers(context, record, receipt, [(name, "gzip")]), context)


def test_parse_rejects_bad_content_type_and_content_length():
    context, record, receipt, _, _, _ = _valid_bundle()
    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "Content-Type" else ("Content-Type", "application/json") for p in pairs]
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)

    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "Content-Length" else ("Content-Length", "04096") for p in pairs]
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)

    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "Content-Length" else ("Content-Length", "1") for p in pairs]
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)


def test_parse_rejects_metadata_too_large_nonascii_and_constants():
    context, record, receipt, _, _, _ = _valid_bundle()
    huge = _metadata_json(context, record, receipt) + (" " * 9000)
    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "X-SG-Import-Metadata" else (p[0], huge) for p in pairs]
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)

    bad_ctx = dict(context)
    bad_ctx["instanceId"] = "inst\x01"
    meta = _metadata_json(bad_ctx, record, receipt)
    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "X-SG-Import-Metadata" else (p[0], meta) for p in pairs]
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)

    const_meta = json.dumps(
        {"context": context, "record": record, "remote_receipt": receipt, "extra": True},
        separators=(",", ":"),
    )
    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "X-SG-Import-Metadata" else (p[0], const_meta) for p in pairs]
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(pairs, context)


def test_parse_rejects_mismatched_trusted_context():
    context, record, receipt, _, _, _ = _valid_bundle()
    wrong = dict(context)
    wrong["keyId"] = "key-2"
    with pytest.raises(RuntimeError, match=_HOLD):
        parse_import_headers(_headers(context, record, receipt), wrong)


def test_validate_import_result_all_four_bool_combinations():
    context, record, receipt, _, _, _ = _valid_bundle()
    parsed_ctx, parsed_rec, parsed_rcpt = parse_import_headers(
        _headers(context, record, receipt),
        context,
    )
    for stage in (False, True):
        for journal in (False, True):
            raw = _import_result(parsed_ctx, parsed_rec, stage, journal)
            out = validate_import_result(raw, parsed_ctx, parsed_rec, parsed_rcpt)
            assert out["replay_stage"] is stage
            assert out["replay_journal"] is journal
            assert type(out["replay_stage"]) is bool
            assert type(out["replay_journal"]) is bool


def test_validate_import_result_detaches_nested_copies():
    context, record, receipt, _, _, _ = _valid_bundle()
    parsed_ctx, parsed_rec, parsed_rcpt = parse_import_headers(
        _headers(context, record, receipt),
        context,
    )
    raw = _import_result(parsed_ctx, parsed_rec, False, True)
    out = validate_import_result(raw, parsed_ctx, parsed_rec, parsed_rcpt)
    assert out["context"] == parsed_ctx
    assert out["artifact"] == parsed_rec["artifact"]
    assert out["context"] is not raw["context"]
    assert out["artifact"] is not raw["artifact"]
    out["context"]["keyId"] = "mutated"
    out["artifact"]["bytes"] = 1
    assert raw["context"]["keyId"] == parsed_ctx["keyId"]
    assert raw["artifact"]["bytes"] == parsed_rec["artifact"]["bytes"]


def test_validate_import_result_rejects_shape_and_type_errors():
    context, record, receipt, _, _, _ = _valid_bundle()
    parsed_ctx, parsed_rec, parsed_rcpt = parse_import_headers(
        _headers(context, record, receipt),
        context,
    )
    base = _import_result(parsed_ctx, parsed_rec, False, False)

    missing = dict(base)
    del missing["replay_journal"]
    with pytest.raises(RuntimeError, match=_HOLD):
        validate_import_result(missing, parsed_ctx, parsed_rec, parsed_rcpt)

    extra = dict(base)
    extra["extra"] = "x"
    with pytest.raises(RuntimeError, match=_HOLD):
        validate_import_result(extra, parsed_ctx, parsed_rec, parsed_rcpt)

    bad_flags = dict(base)
    bad_flags["replay_stage"] = "false"
    with pytest.raises(RuntimeError, match=_HOLD):
        validate_import_result(bad_flags, parsed_ctx, parsed_rec, parsed_rcpt)

    nested = dict(base)
    nested["replay_journal"] = {"x": 1}
    with pytest.raises(RuntimeError, match=_HOLD):
        validate_import_result(nested, parsed_ctx, parsed_rec, parsed_rcpt)

    class SubDict(dict):
        pass

    sub = dict(base)
    sub["context"] = SubDict(sub["context"])
    with pytest.raises(RuntimeError, match=_HOLD):
        validate_import_result(sub, parsed_ctx, parsed_rec, parsed_rcpt)

    mutated = dict(base)
    mutated["job_id"] = "cd" * 16
    with pytest.raises(RuntimeError, match=_HOLD):
        validate_import_result(mutated, parsed_ctx, parsed_rec, parsed_rcpt)


def test_diagnostic_redaction_and_interrupt_propagation():
    context, record, receipt, _, _, _ = _valid_bundle()
    pairs = _headers(context, record, receipt)
    pairs = [p if p[0] != "Content-Type" else ("Content-Type", "bad") for p in pairs]
    try:
        parse_import_headers(pairs, context)
    except RuntimeError as exc:
        assert str(exc) == _HOLD
        assert "bad" not in str(exc)
        assert "Content-Type" not in str(exc)
    else:
        raise AssertionError("expected hold")

    def boom(*_a, **_k):
        raise KeyboardInterrupt

    import lib.runtime_import_http_contract as mod

    orig = mod.validate_remote_cipher_metadata
    mod.validate_remote_cipher_metadata = boom
    try:
        with pytest.raises(KeyboardInterrupt):
            parse_import_headers(_headers(context, record, receipt), context)
    finally:
        mod.validate_remote_cipher_metadata = orig

    def exit_boom(*_a, **_k):
        raise SystemExit(9)

    mod.validate_remote_cipher_metadata = exit_boom
    try:
        with pytest.raises(SystemExit):
            validate_import_result(
                _import_result(context, record, True, True),
                context,
                record,
                receipt,
            )
    finally:
        mod.validate_remote_cipher_metadata = orig

@pytest.mark.parametrize("value", ["0", "00", "01", "+4096", "4096 ", " 4096", "4096,4096", "67113001", "999999999", "4.096", "٤٠٩٦"])
def test_independent_noncanonical_length(value):
    ctx, rec, receipt, *_ = _valid_bundle()
    pairs = [(k, value if k == "Content-Length" else v) for k,v in _headers(ctx,rec,receipt)]
    with pytest.raises(RuntimeError, match="^Import HTTP contract held$"):
        parse_import_headers(pairs,ctx)

@pytest.mark.parametrize("name", ["Bad:Name", "Bad(Name", "Bad/Name", "Bad Name", "Bad\tName", "Bad\rName"])
def test_independent_invalid_header_token(name):
    ctx,rec,receipt,*_ = _valid_bundle()
    with pytest.raises(RuntimeError, match="^Import HTTP contract held$"):
        parse_import_headers(_headers(ctx,rec,receipt,[(name,"x")]),ctx)

@pytest.mark.parametrize("flags", [(0,False),(False,1),("false",True),(True,None)])
def test_independent_result_flags(flags):
    ctx,rec,receipt,*_ = _valid_bundle()
    raw = _import_result(ctx,rec,*flags)
    with pytest.raises(RuntimeError, match="^Import HTTP contract held$"):
        validate_import_result(raw,ctx,rec,receipt)

@pytest.mark.parametrize("size", [1,67113000])
def test_independent_content_length_boundaries(size):
    ctx,rec,receipt,*_ = _valid_bundle(size)
    assert parse_import_headers(_headers(ctx,rec,receipt),ctx)[1]["artifact"]["bytes"] == size

@pytest.mark.parametrize("extra", [0,1])
def test_independent_exact_metadata_cap(extra):
    ctx,rec,receipt,*_ = _valid_bundle()
    metadata = _metadata_json(ctx,rec,receipt)
    padded = metadata + " " * (8192 + extra - len(metadata))
    pairs = [(k,padded if k == "X-SG-Import-Metadata" else v) for k,v in _headers(ctx,rec,receipt)]
    if extra:
        with pytest.raises(RuntimeError, match="^Import HTTP contract held$"):
            parse_import_headers(pairs,ctx)
    else:
        assert parse_import_headers(pairs,ctx)[0] == ctx

@pytest.mark.parametrize("field,value", [("bytes",True),("bytes",4096.0),("sha256","e"*64),("leaf","foreign.bin")])
def test_independent_result_artifact(field,value):
    ctx,rec,receipt,*_ = _valid_bundle()
    raw = _import_result(ctx,rec,False,False)
    raw["artifact"][field] = value
    with pytest.raises(RuntimeError, match="^Import HTTP contract held$"):
        validate_import_result(raw,ctx,rec,receipt)

def test_independent_redacted_rendered_exception(monkeypatch):
    import traceback
    import lib.runtime_import_http_contract as mod
    ctx,rec,receipt,*_ = _valid_bundle()
    def boom(*args):
        raise ValueError("SECRET-FAULT-MARKER")
    monkeypatch.setattr(mod,"validate_remote_cipher_metadata",boom)
    for operation in (lambda: parse_import_headers(_headers(ctx,rec,receipt),ctx),lambda: validate_import_result(_import_result(ctx,rec,False,True),ctx,rec,receipt)):
        with pytest.raises(RuntimeError,match="^Import HTTP contract held$") as caught:
            operation()
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__ is True
        assert "SECRET-FAULT-MARKER" not in "".join(traceback.format_exception(caught.type,caught.value,caught.tb))

@pytest.mark.parametrize("target", ["context","record","receipt"])
def test_independent_declared_metadata_revalidated(target):
    ctx,rec,receipt,*_ = _valid_bundle()
    raw = _import_result(ctx,rec,False,True)
    if target == "context": ctx["keyId"] = "other-key"
    elif target == "record": rec["schema"] = "invented"
    else: receipt["object_version"] = receipt["commit_version"]
    with pytest.raises(RuntimeError,match="^Import HTTP contract held$"):
        validate_import_result(raw,ctx,rec,receipt)

@pytest.mark.parametrize("location", ["result","context","artifact"])
def test_independent_dict_subclass_magic_not_called(location):
    class Trap(dict):
        def __eq__(self,other): raise AssertionError("untrusted equality")
        def __iter__(self): raise AssertionError("untrusted iteration")
        def __len__(self): raise AssertionError("untrusted length")
    ctx,rec,receipt,*_ = _valid_bundle()
    raw = _import_result(ctx,rec,False,True)
    if location == "result": raw = Trap(raw)
    else: raw[location] = Trap(raw[location])
    with pytest.raises(RuntimeError,match="^Import HTTP contract held$") as caught:
        validate_import_result(raw,ctx,rec,receipt)
    assert caught.value.__context__ is None or type(caught.value.__context__) is RuntimeError

def test_independent_parse_detaches_all_nested_outputs():
    ctx,rec,receipt,*_ = _valid_bundle()
    outctx,outrec,outreceipt = parse_import_headers(_headers(ctx,rec,receipt),ctx)
    assert outctx is not outreceipt["context"]
    assert outrec["artifact"] is not outreceipt["artifact"]
    outctx["keyId"] = "changed"
    outrec["artifact"]["bytes"] = 1
    assert outreceipt["context"] == ctx
    assert outreceipt["artifact"] == receipt["artifact"]

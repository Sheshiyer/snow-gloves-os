"""Linux-only remote cipher staging and journal binding contract."""
from __future__ import annotations

import os
import stat
import sys
import threading
import time
from typing import Any

try:
    from .runtime_job_journal import LocalJobJournal
    from .runtime_remote_cipher_stage import stage_remote_cipher
    from .runtime_storage_guard import StorageBudget, preflight
except ImportError:
    from lib.runtime_job_journal import LocalJobJournal
    from lib.runtime_remote_cipher_stage import stage_remote_cipher
    from lib.runtime_storage_guard import StorageBudget, preflight

_TIMEOUT_SECONDS = 15.0


def _hold() -> None:
    raise RuntimeError("Remote cipher import held") from None


def _check_deadline_cancel(deadline: float, cancel_event: threading.Event) -> None:
    if type(cancel_event) is not threading.Event or cancel_event.is_set():
        _hold()
    if time.monotonic() >= deadline:
        _hold()


def _full_sig(st: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        st.st_dev,
        st.st_ino,
        st.st_mode,
        st.st_uid,
        st.st_nlink,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
    )


def _verify_root_guard(
    root_path: str,
    exp_id: tuple[int, int, int, int],
    deadline: float,
    cancel_event: threading.Event,
) -> None:
    _check_deadline_cancel(deadline, cancel_event)
    if sys.platform != "linux" or type(root_path) is not str or not os.path.isabs(root_path):
        _hold()
    if len(root_path.encode("utf-8", errors="surrogateescape")) > 4096:
        _hold()
    if os.path.realpath(root_path) != root_path or os.path.normpath(root_path) != root_path:
        _hold()
    if root_path in ("/", "/.", "/.."):
        _hold()

    cur = "/"
    for part in [p for p in root_path.split("/") if p]:
        _check_deadline_cancel(deadline, cancel_event)
        cur = cur + part if cur == "/" else f"{cur}/{part}"
        try:
            st = os.lstat(cur)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if stat.S_ISLNK(st.st_mode):
            _hold()

    exp_dev, exp_ino, exp_uid, exp_mode = exp_id
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        root_fd = os.open(root_path, flags)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()
    try:
        st_fd = os.fstat(root_fd)
        st_named = os.lstat(root_path)
        if not stat.S_ISDIR(st_fd.st_mode) or (st_fd.st_mode & 0o7000) != 0 or stat.S_IMODE(st_fd.st_mode) != exp_mode:
            _hold()
        if st_fd.st_dev != exp_dev or st_fd.st_ino != exp_ino or st_fd.st_uid != exp_uid:
            _hold()
        if not stat.S_ISDIR(st_named.st_mode) or (st_named.st_mode & 0o7000) != 0 or stat.S_IMODE(st_named.st_mode) != exp_mode:
            _hold()
        if st_named.st_dev != exp_dev or st_named.st_ino != exp_ino or st_named.st_uid != exp_uid:
            _hold()
        if _full_sig(st_fd) != _full_sig(st_named):
            _hold()
    finally:
        try:
            os.close(root_fd)
        except Exception:
            _hold()
    _check_deadline_cancel(deadline, cancel_event)


def _strict_copy_scalar_dict(src: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
    if type(src) is not dict or len(src) != len(allowed_keys) or any(type(k) is not str for k in src) or set(src.keys()) != allowed_keys:
        _hold()
    out: dict[str, Any] = {}
    for k, v in src.items():
        if type(k) is not str:
            _hold()
        if type(v) is str or (type(v) is int and type(v) is not bool):
            out[k] = v
        else:
            _hold()
    return out


def _verified_record_matches(value, expected):
    if type(value) is not dict or len(value) != 5 or any(type(k) is not str for k in value):
        return False
    if set(value) != {"schema", "job_id", "request_digest", "state", "artifact"}:
        return False
    if any(type(value[k]) is not str for k in ("schema", "job_id", "request_digest", "state")):
        return False
    artifact = value["artifact"]
    if type(artifact) is not dict or len(artifact) != 3 or any(type(k) is not str for k in artifact):
        return False
    if set(artifact) != {"leaf", "bytes", "sha256"}:
        return False
    if type(artifact["leaf"]) is not str or type(artifact["bytes"]) is not int or type(artifact["sha256"]) is not str:
        return False
    return value == expected


def import_remote_cipher_and_bind_journal(
    root_path: str,
    expected_identity: tuple[Any, ...],
    context: dict[str, Any],
    record: dict[str, Any],
    receipt: dict[str, Any],
    input_fd: int,
    cancel_event: threading.Event,
    *,
    deadline=None,
) -> dict[str, Any]:
    effective_deadline: float | None = None

    try:
        start_time = time.monotonic()
        if deadline is None:
            effective_deadline = start_time + _TIMEOUT_SECONDS
        else:
            if (type(deadline) is not int and type(deadline) is not float) or isinstance(deadline, bool):
                _hold()
            if not (deadline > start_time) or deadline > start_time + _TIMEOUT_SECONDS:
                _hold()
            effective_deadline = deadline

        _check_deadline_cancel(effective_deadline, cancel_event)

        if type(expected_identity) is not tuple or len(expected_identity) != 4:
            _hold()
        for x in expected_identity:
            if type(x) is not int or isinstance(x, bool):
                _hold()
        exp_dev, exp_ino, exp_uid, exp_mode = expected_identity
        if exp_dev <= 0 or exp_ino <= 0 or exp_uid < 0 or exp_mode != 0o700 or exp_uid != os.geteuid():
            _hold()
        exp_id = (exp_dev, exp_ino, exp_uid, exp_mode)

        if type(input_fd) is not int or isinstance(input_fd, bool) or input_fd < 0:
            _hold()

        ctx_keys = {"instanceId", "runtimeVersion", "imageDigest", "keyId"}
        copied_ctx = _strict_copy_scalar_dict(context, ctx_keys)
        for k in ctx_keys:
            if type(copied_ctx[k]) is not str:
                _hold()
        if len(copied_ctx["instanceId"]) > 64 or len(copied_ctx["runtimeVersion"]) > 16 or len(copied_ctx["imageDigest"]) > 64 or len(copied_ctx["keyId"]) > 64:
            _hold()

        if type(record) is not dict or len(record) != 5 or set(record.keys()) != {"schema", "job_id", "request_digest", "state", "artifact"}:
            _hold()
        art_src = record["artifact"]
        copied_art = _strict_copy_scalar_dict(art_src, {"leaf", "bytes", "sha256"})
        if type(copied_art["leaf"]) is not str or type(copied_art["bytes"]) is not int or type(copied_art["sha256"]) is not str:
            _hold()
        if len(copied_art["leaf"]) > 80 or len(copied_art["sha256"]) > 64 or not (1 <= copied_art["bytes"] <= 64 * 1024 * 1024 + 4136):
            _hold()

        if type(record["schema"]) is not str or type(record["job_id"]) is not str or type(record["request_digest"]) is not str or type(record["state"]) is not str:
            _hold()
        if len(record["job_id"]) > 32 or len(record["request_digest"]) > 64:
            _hold()
        copied_rec = {
            "schema": record["schema"],
            "job_id": record["job_id"],
            "request_digest": record["request_digest"],
            "state": record["state"],
            "artifact": dict(copied_art),
        }

        receipt_keys = {
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
        }
        if type(receipt) is not dict or len(receipt) != 10 or set(receipt.keys()) != receipt_keys:
            _hold()
        rcpt_ctx = _strict_copy_scalar_dict(receipt["context"], ctx_keys)
        rcpt_art = _strict_copy_scalar_dict(receipt["artifact"], {"leaf", "bytes", "sha256"})
        for k in ("schema", "state", "job_id", "request_digest", "object_key", "object_version", "commit_key", "commit_version"):
            if type(receipt[k]) is not str:
                _hold()
        if len(receipt["object_key"]) > 1024 or len(receipt["commit_key"]) > 1024 or len(receipt["object_version"]) > 256 or len(receipt["commit_version"]) > 256:
            _hold()
        for k in ctx_keys:
            if type(rcpt_ctx[k]) is not str or len(rcpt_ctx[k]) > {"instanceId": 64, "runtimeVersion": 16, "imageDigest": 64, "keyId": 64}[k]:
                _hold()
        if type(rcpt_art["leaf"]) is not str or type(rcpt_art["bytes"]) is not int or type(rcpt_art["sha256"]) is not str:
            _hold()
        if len(rcpt_art["leaf"]) > 80 or len(rcpt_art["sha256"]) > 64 or not (1 <= rcpt_art["bytes"] <= 64 * 1024 * 1024 + 4136):
            _hold()
        if len(receipt["schema"]) > 64 or len(receipt["state"]) > 64 or len(receipt["job_id"]) > 32 or len(receipt["request_digest"]) > 64 or len(copied_rec["schema"]) > 64 or len(copied_rec["state"]) > 64:
            _hold()
        copied_rcpt = {
            "schema": receipt["schema"],
            "state": receipt["state"],
            "context": dict(rcpt_ctx),
            "job_id": receipt["job_id"],
            "request_digest": receipt["request_digest"],
            "artifact": dict(rcpt_art),
            "object_key": receipt["object_key"],
            "object_version": receipt["object_version"],
            "commit_key": receipt["commit_key"],
            "commit_version": receipt["commit_version"],
        }

        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)

        try:
            stage_res = stage_remote_cipher(
                root_path,
                exp_id,
                copied_ctx,
                copied_rec,
                copied_rcpt,
                input_fd,
                cancel_event,
                deadline=effective_deadline,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _check_deadline_cancel(effective_deadline, cancel_event)
        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)

        stage_keys = {"schema", "state", "context", "job_id", "request_digest", "artifact", "replay_historical"}
        if type(stage_res) is not dict or len(stage_res) != 7 or set(stage_res.keys()) != stage_keys:
            _hold()
        if stage_res["schema"] != "sg.local-cipher-stage.v1" or stage_res["state"] != "cipher-staged":
            _hold()
        if type(stage_res["replay_historical"]) is not bool:
            _hold()
        if type(stage_res["context"]) is not dict or len(stage_res["context"]) != 4 or stage_res["context"] != copied_ctx:
            _hold()
        if stage_res["job_id"] != copied_rec["job_id"] or stage_res["request_digest"] != copied_rec["request_digest"]:
            _hold()
        if type(stage_res["artifact"]) is not dict or len(stage_res["artifact"]) != 3 or stage_res["artifact"] != copied_art:
            _hold()
        art_res = stage_res["artifact"]
        if type(art_res["leaf"]) is not str or type(art_res["bytes"]) is not int or type(art_res["bytes"]) is bool or type(art_res["sha256"]) is not str:
            _hold()

        replay_stage_flag = stage_res["replay_historical"]
        bound_job_id = stage_res["job_id"]
        bound_req_digest = stage_res["request_digest"]
        bound_art = {
            "leaf": stage_res["artifact"]["leaf"],
            "bytes": stage_res["artifact"]["bytes"],
            "sha256": stage_res["artifact"]["sha256"],
        }

        expected_verified_record = {
            "schema": "sg.local-job.v1",
            "job_id": bound_job_id,
            "request_digest": bound_req_digest,
            "state": "artifact-verified",
            "artifact": dict(bound_art),
        }

        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
        try:
            journal = LocalJobJournal(root_path)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
        try:
            existing_rec = journal.lookup(bound_job_id, bound_req_digest)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)

        replay_journal_flag = False

        if existing_rec is not None:
            if type(existing_rec) is not dict or len(existing_rec) != 5 or set(existing_rec.keys()) != {"schema", "job_id", "request_digest", "state", "artifact"}:
                _hold()
            if existing_rec["schema"] != "sg.local-job.v1" or existing_rec["job_id"] != bound_job_id or existing_rec["request_digest"] != bound_req_digest:
                _hold()
            if existing_rec["state"] == "artifact-verified":
                if not _verified_record_matches(existing_rec, expected_verified_record):
                    _hold()
                replay_journal_flag = True
            elif existing_rec["state"] == "prepared":
                if existing_rec.get("artifact") is not None:
                    _hold()
                replay_journal_flag = False
            else:
                _hold()

        if not replay_journal_flag:
            if replay_stage_flag:
                _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
                try:
                    preflight(root_path, exp_id, "checkpoint_encrypt", StorageBudget())
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    _hold()
                _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)

            if existing_rec is None:
                _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
                try:
                    prep_res = journal.prepare(bound_job_id, bound_req_digest)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    _hold()
                _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
                if type(prep_res) is not dict or len(prep_res) != 5 or set(prep_res.keys()) != {"schema", "job_id", "request_digest", "state", "artifact"}:
                    _hold()
                if prep_res["schema"] != "sg.local-job.v1" or prep_res["job_id"] != bound_job_id or prep_res["request_digest"] != bound_req_digest:
                    _hold()
                if prep_res.get("state") == "artifact-verified":
                    if not _verified_record_matches(prep_res, expected_verified_record):
                        _hold()
                elif prep_res.get("state") == "prepared":
                    if prep_res.get("artifact") is not None:
                        _hold()
                else:
                    _hold()

            _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
            try:
                rec_res = journal.record_artifact(
                    bound_job_id,
                    bound_req_digest,
                    bound_art["leaf"],
                    bound_art["bytes"],
                    bound_art["sha256"],
                )
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()
            _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
            if not _verified_record_matches(rec_res, expected_verified_record):
                _hold()

        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
        try:
            final_lookup = journal.lookup(bound_job_id, bound_req_digest)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
        if not _verified_record_matches(final_lookup, expected_verified_record):
            _hold()

        result = {
            "schema": "sg.local-cipher-import.v1",
            "state": "cipher-journal-bound",
            "context": dict(copied_ctx),
            "job_id": bound_job_id,
            "request_digest": bound_req_digest,
            "artifact": dict(bound_art),
            "replay_stage": replay_stage_flag,
            "replay_journal": replay_journal_flag,
        }

        _verify_root_guard(root_path, exp_id, effective_deadline, cancel_event)
        _check_deadline_cancel(effective_deadline, cancel_event)
        return result
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()
    finally:
        exc_type, exc_val, exc_tb = sys.exc_info()
        try:
            if effective_deadline is not None:
                _check_deadline_cancel(effective_deadline, cancel_event)
        except (KeyboardInterrupt, SystemExit):
            if isinstance(exc_val, (KeyboardInterrupt, SystemExit)):
                raise exc_val.with_traceback(exc_tb)
            raise
        except Exception:
            if isinstance(exc_val, (KeyboardInterrupt, SystemExit)):
                raise exc_val.with_traceback(exc_tb)
            _hold()

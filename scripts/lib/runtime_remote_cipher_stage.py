"""Linux-only remote ciphertext staging contract."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import hmac
import os
import re
import secrets
import select
import stat
import sys
import threading
import time
from typing import Any

try:
    from .runtime_operation_identity import checkpoint_digest
    from .runtime_storage_guard import StorageBudget, preflight
except ImportError:
    from lib.runtime_operation_identity import checkpoint_digest
    from lib.runtime_storage_guard import StorageBudget, preflight

_TIMEOUT_SECONDS = 15.0
_CHUNK_SIZE = 65536
_MAX_CIPHERTEXT_SIZE = 64 * 1024 * 1024 + 4136
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def _hold() -> None:
    raise RuntimeError("Remote cipher staging held") from None


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


def _check_deadline_cancel(deadline: float, cancel_event: threading.Event) -> None:
    if type(cancel_event) is not threading.Event or cancel_event.is_set():
        _hold()
    if time.monotonic() >= deadline:
        _hold()


def _validate_root_path(root_path: str, deadline: float, cancel_event: threading.Event) -> str:
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
    _check_deadline_cancel(deadline, cancel_event)
    return root_path


def _validate_ascii_version(val: Any) -> str:
    if type(val) is not str or not (1 <= len(val) <= 256):
        _hold()
    for c in val:
        if ord(c) < 33 or ord(c) > 126:
            _hold()
    return val


def _validate_inputs(
    root_path: str,
    expected_identity: tuple[Any, ...],
    context: dict[str, Any],
    record: dict[str, Any],
    receipt: dict[str, Any],
    input_fd: int,
    cancel_event: threading.Event,
    deadline: float,
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any], str, str, dict[str, Any], tuple[int, int, int, int]]:
    _check_deadline_cancel(deadline, cancel_event)

    if type(expected_identity) is not tuple or len(expected_identity) != 4:
        _hold()
    for x in expected_identity:
        if type(x) is not int or isinstance(x, bool):
            _hold()
    exp_dev, exp_ino, exp_uid, exp_mode = expected_identity
    if exp_dev <= 0 or exp_ino <= 0 or exp_uid < 0 or exp_mode != 0o700 or exp_uid != os.geteuid():
        _hold()

    if type(input_fd) is not int or isinstance(input_fd, bool) or input_fd < 0:
        _hold()

    if type(context) is not dict or set(context.keys()) != {"instanceId", "runtimeVersion", "imageDigest", "keyId"}:
        _hold()
    for k, v in context.items():
        if type(v) is not str:
            _hold()
    if context["runtimeVersion"] != "3.8.50":
        _hold()
    if not _ID_RE.fullmatch(context["instanceId"]):
        _hold()
    if not _ID_RE.fullmatch(context["keyId"]):
        _hold()
    if not _HEX64_RE.fullmatch(context["imageDigest"]):
        _hold()
    validated_ctx = {
        "instanceId": context["instanceId"],
        "runtimeVersion": context["runtimeVersion"],
        "imageDigest": context["imageDigest"],
        "keyId": context["keyId"],
    }

    if type(record) is not dict or set(record.keys()) != {"schema", "job_id", "request_digest", "state", "artifact"}:
        _hold()
    if type(record["schema"]) is not str or record["schema"] != "sg.local-job.v1":
        _hold()
    job_id = record["job_id"]
    req_digest = record["request_digest"]
    if type(job_id) is not str or not _HEX32_RE.fullmatch(job_id):
        _hold()
    if type(req_digest) is not str or not _HEX64_RE.fullmatch(req_digest):
        _hold()
    if type(record["state"]) is not str or record["state"] != "artifact-verified":
        _hold()

    try:
        expected_req_digest = checkpoint_digest(validated_ctx, job_id)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()
    if not hmac.compare_digest(req_digest, expected_req_digest):
        _hold()

    art = record["artifact"]
    if type(art) is not dict or set(art.keys()) != {"leaf", "bytes", "sha256"}:
        _hold()
    leaf = art["leaf"]
    b_count = art["bytes"]
    s256 = art["sha256"]
    if type(leaf) is not str or leaf != f"sg-encrypted-{job_id}.bin":
        _hold()
    if type(b_count) is not int or isinstance(b_count, bool) or not (1 <= b_count <= _MAX_CIPHERTEXT_SIZE):
        _hold()
    if type(s256) is not str or not _HEX64_RE.fullmatch(s256):
        _hold()
    validated_art = {"leaf": leaf, "bytes": b_count, "sha256": s256}
    validated_rec = {
        "schema": "sg.local-job.v1",
        "job_id": job_id,
        "request_digest": req_digest,
        "state": "artifact-verified",
        "artifact": copy.deepcopy(validated_art),
    }

    exp_prefix = f"cp/v1/{validated_ctx['instanceId']}/{validated_ctx['imageDigest']}/{job_id}/{req_digest}/{s256}"
    exp_obj_key = f"{exp_prefix}.bin"
    exp_commit_key = f"{exp_prefix}.commit.json"

    if type(receipt) is not dict or set(receipt.keys()) != {
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
    }:
        _hold()
    if any(type(receipt[k]) is not str for k in ("schema", "state", "job_id", "request_digest", "object_key", "object_version", "commit_key", "commit_version")):
        _hold()
    if type(receipt["context"]) is not dict or set(receipt["context"]) != set(validated_ctx) or any(type(v) is not str for v in receipt["context"].values()):
        _hold()
    if type(receipt["artifact"]) is not dict or set(receipt["artifact"]) != set(validated_art):
        _hold()
    if type(receipt["artifact"]["bytes"]) is not int or any(type(receipt["artifact"][k]) is not str for k in ("leaf","sha256")):
        _hold()
    if receipt["schema"] != "sg.remote-checkpoint.v1" or receipt["state"] != "remote-committed":
        _hold()
    if receipt["context"] != validated_ctx:
        _hold()
    if receipt["job_id"] != job_id:
        _hold()
    if type(receipt["request_digest"]) is not str or not hmac.compare_digest(receipt["request_digest"], req_digest):
        _hold()
    if receipt["artifact"] != validated_art:
        _hold()
    if receipt["object_key"] != exp_obj_key or receipt["commit_key"] != exp_commit_key:
        _hold()
    o_ver = _validate_ascii_version(receipt["object_version"])
    c_ver = _validate_ascii_version(receipt["commit_version"])
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

    return validated_ctx, validated_rec, validated_receipt, job_id, req_digest, validated_art, (exp_dev, exp_ino, exp_uid, exp_mode)


def _verify_root_guard(
    root_path: str,
    root_fd: int,
    exp_id: tuple[int, int, int, int],
    deadline: float,
    cancel_event: threading.Event,
) -> None:
    _check_deadline_cancel(deadline, cancel_event)
    try:
        st_fd = os.fstat(root_fd)
        st_named = os.lstat(root_path)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()
    exp_dev, exp_ino, exp_uid, exp_mode = exp_id
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
    if os.path.realpath(root_path) != root_path:
        _hold()
    _check_deadline_cancel(deadline, cancel_event)


def _stream_hash_and_verify(
    fd: int,
    expected_size: int,
    expected_sha: str,
    deadline: float,
    cancel_event: threading.Event,
) -> None:
    hasher = hashlib.sha256()
    total = 0
    try:
        os.lseek(fd, 0, os.SEEK_SET)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()
    while True:
        _check_deadline_cancel(deadline, cancel_event)
        try:
            chunk = os.read(fd, _CHUNK_SIZE)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if not chunk:
            break
        total += len(chunk)
        if total > expected_size:
            _hold()
        hasher.update(chunk)
    if total != expected_size or hasher.hexdigest() != expected_sha:
        _hold()
    _check_deadline_cancel(deadline, cancel_event)


def stage_remote_cipher(
    root_path: str,
    expected_identity: tuple[Any, ...],
    context: dict[str, Any],
    record: dict[str, Any],
    receipt: dict[str, Any],
    input_fd: int,
    cancel_event: threading.Event,
) -> dict[str, Any]:
    start_time = time.monotonic()
    deadline = start_time + _TIMEOUT_SECONDS

    root_fd: int | None = None
    dup_in_fd: int | None = None
    temp_fd: int | None = None
    temp_name: str | None = None
    existing_fd: int | None = None
    final_fd: int | None = None
    cleanup_failed = False

    try:
        _check_deadline_cancel(deadline, cancel_event)
        validated_ctx, validated_rec, validated_rcpt, job_id, req_digest, art, exp_id = _validate_inputs(
            root_path, expected_identity, context, record, receipt, input_fd, cancel_event, deadline
        )
        v_root = _validate_root_path(root_path, deadline, cancel_event)

        try:
            caller_flags = fcntl.fcntl(input_fd, fcntl.F_GETFL)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if (caller_flags & os.O_NONBLOCK) == 0 or (caller_flags & os.O_ACCMODE) not in (os.O_RDONLY, os.O_RDWR):
            _hold()
        try:
            st_src = os.fstat(input_fd)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if stat.S_ISREG(st_src.st_mode) or stat.S_ISDIR(st_src.st_mode) or stat.S_ISLNK(st_src.st_mode):
            _hold()
        if not (stat.S_ISFIFO(st_src.st_mode) or stat.S_ISSOCK(st_src.st_mode)):
            _hold()
        if st_src.st_uid != os.geteuid():
            _hold()

        final_leaf = art["leaf"]
        expected_size = art["bytes"]
        expected_sha = art["sha256"]

        root_open_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            root_fd = os.open(v_root, root_open_flags)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)

        final_exists = False
        try:
            existing_fd = os.open(final_leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=root_fd)
            final_exists = True
        except FileNotFoundError:
            final_exists = False
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        if final_exists and existing_fd is not None:
            try:
                st_f1 = os.fstat(existing_fd)
                st_named1 = os.lstat(final_leaf, dir_fd=root_fd)
                if not stat.S_ISREG(st_f1.st_mode) or (st_f1.st_mode & 0o7000) != 0 or stat.S_IMODE(st_f1.st_mode) != 0o600:
                    _hold()
                if st_f1.st_dev != exp_id[0] or st_f1.st_uid != exp_id[2] or st_f1.st_nlink != 1:
                    _hold()
                if st_f1.st_size != expected_size:
                    _hold()
                if _full_sig(st_f1) != _full_sig(st_named1):
                    _hold()

                _stream_hash_and_verify(existing_fd, expected_size, expected_sha, deadline, cancel_event)

                st_f2 = os.fstat(existing_fd)
                st_named2 = os.lstat(final_leaf, dir_fd=root_fd)
                if _full_sig(st_f1) != _full_sig(st_f2) or _full_sig(st_f1) != _full_sig(st_named2):
                    _hold()

                _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
                _validate_root_path(v_root, deadline, cancel_event)

                return {
                    "schema": "sg.local-cipher-stage.v1",
                    "state": "cipher-staged",
                    "context": copy.deepcopy(validated_ctx),
                    "job_id": job_id,
                    "request_digest": req_digest,
                    "artifact": copy.deepcopy(art),
                    "replay_historical": True,
                }
            finally:
                try:
                    os.close(existing_fd)
                except Exception:
                    cleanup_failed = True
                existing_fd = None

        try:
            preflight(v_root, exp_id, "checkpoint_encrypt", StorageBudget())
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)

        try:
            flags_before = fcntl.fcntl(input_fd, fcntl.F_GETFL)
            if (flags_before & os.O_NONBLOCK) == 0 or (flags_before & os.O_ACCMODE) not in (os.O_RDONLY, os.O_RDWR):
                _hold()
            dup_in_fd = os.dup(input_fd)
            fcntl.fcntl(dup_in_fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
            flags_dup = fcntl.fcntl(dup_in_fd, fcntl.F_GETFL)
            flags_after = fcntl.fcntl(input_fd, fcntl.F_GETFL)
            if (flags_dup & os.O_NONBLOCK) == 0 or flags_before != flags_after:
                _hold()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        st_dup = os.fstat(dup_in_fd)
        if st_dup.st_dev != st_src.st_dev or st_dup.st_ino != st_src.st_ino or st_dup.st_uid != exp_id[2]:
            _hold()

        for attempt in range(8):
            _check_deadline_cancel(deadline, cancel_event)
            tok = secrets.token_hex(8)
            candidate_temp = f".sg-remote-stage-{job_id}-{tok}.part"
            _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
            try:
                temp_fd = os.open(
                    candidate_temp,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=root_fd,
                )
                temp_name = candidate_temp
                break
            except FileExistsError:
                if attempt == 7:
                    _hold()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()

        if temp_fd is None or temp_name is None:
            _hold()

        st_t_init = os.fstat(temp_fd)
        st_t_named_init = os.lstat(temp_name, dir_fd=root_fd)
        if not stat.S_ISREG(st_t_init.st_mode) or (st_t_init.st_mode & 0o7000) != 0 or stat.S_IMODE(st_t_init.st_mode) != 0o600:
            _hold()
        if st_t_init.st_dev != exp_id[0] or st_t_init.st_uid != exp_id[2] or st_t_init.st_nlink != 1:
            _hold()
        if _full_sig(st_t_init) != _full_sig(st_t_named_init):
            _hold()

        def verify_owned_temp():
            _check_deadline_cancel(deadline, cancel_event)
            current = os.fstat(temp_fd)
            named = os.lstat(temp_name, dir_fd=root_fd)
            if (current.st_dev, current.st_ino, current.st_uid, current.st_mode) != (st_t_init.st_dev, st_t_init.st_ino, st_t_init.st_uid, st_t_init.st_mode):
                _hold()
            if current.st_nlink != 1 or current.st_size > expected_size or _full_sig(current) != _full_sig(named):
                _hold()
            _check_deadline_cancel(deadline, cancel_event)

        hasher = hashlib.sha256()
        bytes_written = 0

        while True:
            _check_deadline_cancel(deadline, cancel_event)
            rem = deadline - time.monotonic()
            if rem <= 0:
                _hold()
            timeout_poll = min(0.05, rem)
            try:
                r_ready, _, _ = select.select([dup_in_fd], [], [], timeout_poll)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()
            _check_deadline_cancel(deadline, cancel_event)
            if not r_ready:
                continue

            observed_flags = fcntl.fcntl(dup_in_fd, fcntl.F_GETFL)
            if (observed_flags & os.O_NONBLOCK) == 0 or (observed_flags & os.O_ACCMODE) not in (os.O_RDONLY, os.O_RDWR):
                _hold()
            try:
                chunk = os.read(dup_in_fd, _CHUNK_SIZE)
            except BlockingIOError:
                continue
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()

            if not chunk:
                break

            if bytes_written + len(chunk) > expected_size:
                _hold()

            view = memoryview(chunk)
            while len(view) > 0:
                _check_deadline_cancel(deadline, cancel_event)
                _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
                verify_owned_temp()
                try:
                    nw = os.write(temp_fd, view)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    _hold()
                _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
                verify_owned_temp()
                if nw <= 0:
                    _hold()
                view = view[nw:]

            hasher.update(chunk)
            bytes_written += len(chunk)

        if bytes_written != expected_size or hasher.hexdigest() != expected_sha:
            _hold()

        _check_deadline_cancel(deadline, cancel_event)
        _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
        verify_owned_temp()
        try:
            os.fsync(temp_fd)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        _check_deadline_cancel(deadline, cancel_event)

        _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)

        st_t_pre = os.fstat(temp_fd)
        st_t_named_pre = os.lstat(temp_name, dir_fd=root_fd)
        if not stat.S_ISREG(st_t_pre.st_mode) or (st_t_pre.st_mode & 0o7000) != 0 or stat.S_IMODE(st_t_pre.st_mode) != 0o600:
            _hold()
        if st_t_pre.st_dev != exp_id[0] or st_t_pre.st_uid != exp_id[2] or st_t_pre.st_nlink != 1:
            _hold()
        if st_t_pre.st_size != expected_size:
            _hold()
        if _full_sig(st_t_pre) != _full_sig(st_t_named_pre):
            _hold()

        _stream_hash_and_verify(temp_fd, expected_size, expected_sha, deadline, cancel_event)

        st_t_pre2 = os.fstat(temp_fd)
        st_t_named_pre2 = os.lstat(temp_name, dir_fd=root_fd)
        if _full_sig(st_t_pre) != _full_sig(st_t_pre2) or _full_sig(st_t_pre) != _full_sig(st_t_named_pre2):
            _hold()

        _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
        _check_deadline_cancel(deadline, cancel_event)

        try:
            os.link(temp_name, final_leaf, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _check_deadline_cancel(deadline, cancel_event)

        st_t_post_fd = os.fstat(temp_fd)
        st_t_post_named = os.lstat(temp_name, dir_fd=root_fd)
        st_f_post = os.lstat(final_leaf, dir_fd=root_fd)

        if (
            st_t_post_fd.st_dev != exp_id[0]
            or st_t_post_fd.st_uid != exp_id[2]
            or (st_t_post_fd.st_mode & 0o7000) != 0
            or stat.S_IMODE(st_t_post_fd.st_mode) != 0o600
            or not stat.S_ISREG(st_t_post_fd.st_mode)
            or st_t_post_fd.st_nlink != 2
            or st_t_post_fd.st_size != expected_size
        ):
            _hold()

        if _full_sig(st_t_post_fd) != _full_sig(st_t_post_named):
            _hold()

        if (
            st_f_post.st_dev != exp_id[0]
            or st_f_post.st_uid != exp_id[2]
            or (st_f_post.st_mode & 0o7000) != 0
            or stat.S_IMODE(st_f_post.st_mode) != 0o600
            or not stat.S_ISREG(st_f_post.st_mode)
            or st_f_post.st_nlink != 2
            or st_f_post.st_size != expected_size
        ):
            _hold()

        if st_t_post_fd.st_ino != st_f_post.st_ino or st_t_post_fd.st_dev != st_f_post.st_dev:
            _hold()
        if _full_sig(st_t_post_fd) != _full_sig(st_f_post):
            _hold()

        _check_deadline_cancel(deadline, cancel_event)

        _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
        try:
            os.unlink(temp_name, dir_fd=root_fd)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _check_deadline_cancel(deadline, cancel_event)

        try:
            os.fsync(root_fd)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        _check_deadline_cancel(deadline, cancel_event)

        try:
            final_fd = os.open(final_leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=root_fd)
            st_f_final1 = os.fstat(final_fd)
            st_f_final_named1 = os.lstat(final_leaf, dir_fd=root_fd)
            if not stat.S_ISREG(st_f_final1.st_mode) or (st_f_final1.st_mode & 0o7000) != 0 or stat.S_IMODE(st_f_final1.st_mode) != 0o600:
                _hold()
            if st_f_final1.st_dev != exp_id[0] or st_f_final1.st_uid != exp_id[2] or st_f_final1.st_nlink != 1:
                _hold()
            if st_f_final1.st_dev != st_t_init.st_dev or st_f_final1.st_ino != st_t_init.st_ino:
                _hold()
            if st_f_final1.st_size != expected_size:
                _hold()
            if _full_sig(st_f_final1) != _full_sig(st_f_final_named1):
                _hold()

            _stream_hash_and_verify(final_fd, expected_size, expected_sha, deadline, cancel_event)

            st_f_final2 = os.fstat(final_fd)
            st_f_final_named2 = os.lstat(final_leaf, dir_fd=root_fd)
            if _full_sig(st_f_final1) != _full_sig(st_f_final2) or _full_sig(st_f_final1) != _full_sig(st_f_final_named2):
                _hold()
        finally:
            if final_fd is not None:
                try:
                    os.close(final_fd)
                except Exception:
                    cleanup_failed = True
                final_fd = None

        _verify_root_guard(v_root, root_fd, exp_id, deadline, cancel_event)
        _validate_root_path(v_root, deadline, cancel_event)
        _check_deadline_cancel(deadline, cancel_event)

        return {
            "schema": "sg.local-cipher-stage.v1",
            "state": "cipher-staged",
            "context": copy.deepcopy(validated_ctx),
            "job_id": job_id,
            "request_digest": req_digest,
            "artifact": copy.deepcopy(art),
            "replay_historical": False,
        }
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()
    finally:
        if dup_in_fd is not None:
            try:
                os.close(dup_in_fd)
            except Exception:
                cleanup_failed = True
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except Exception:
                cleanup_failed = True
        if existing_fd is not None:
            try:
                os.close(existing_fd)
            except Exception:
                cleanup_failed = True
        if final_fd is not None:
            try:
                os.close(final_fd)
            except Exception:
                cleanup_failed = True
        if root_fd is not None:
            try:
                fcntl.flock(root_fd, fcntl.LOCK_UN)
            except Exception:
                cleanup_failed = True
            try:
                os.close(root_fd)
            except Exception:
                cleanup_failed = True
        if cleanup_failed or type(cancel_event) is not threading.Event or cancel_event.is_set() or time.monotonic() >= deadline:
            _hold()

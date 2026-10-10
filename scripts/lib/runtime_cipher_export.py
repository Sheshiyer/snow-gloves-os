"""Linux-only Verified Owned Ciphertext Reader implementation."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import os
import stat
import sys
import threading
import time
from typing import Any, Generator

try:
    from .runtime_job_journal import _parse_and_validate_record
    from .runtime_operation_identity import validate_checkpoint
except ImportError:
    from lib.runtime_job_journal import _parse_and_validate_record
    from lib.runtime_operation_identity import validate_checkpoint

_MAX_CIPHERTEXT_SIZE = 64 * 1024 * 1024 + 4136
_CHUNK_SIZE = 65536
_TIMEOUT_SECONDS = 15.0
_MAX_JOURNAL_SIZE = 2048


def _hold() -> None:
    raise RuntimeError("Cipher export held") from None


def _stat_sig(st: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        st.st_dev,
        st.st_ino,
        st.st_mode,
        st.st_uid,
        st.st_nlink,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
        st.st_blocks,
    )


def _validate_root_path(root_path: str, deadline: float, cancel_event: threading.Event | None) -> str:
    if time.monotonic() >= deadline:
        _hold()
    if cancel_event is not None and cancel_event.is_set():
        _hold()
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
        if time.monotonic() >= deadline:
            _hold()
        if cancel_event is not None and cancel_event.is_set():
            _hold()
        cur = cur + part if cur == "/" else f"{cur}/{part}"
        try:
            st = os.lstat(cur)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if stat.S_ISLNK(st.st_mode):
            _hold()
    if time.monotonic() >= deadline:
        _hold()
    if cancel_event is not None and cancel_event.is_set():
        _hold()
    return root_path


class CheckpointExportReader:
    def __init__(
        self,
        root: str,
        expected_identity: tuple[int, int, int, int],
        trusted_context: dict[str, Any],
        payload: dict[str, Any],
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._start_time = time.monotonic()
        self._deadline = self._start_time + _TIMEOUT_SECONDS
        self._cancel_event = cancel_event

        self._root_fd: int | None = None
        self._cipher_fd: int | None = None
        self._entered = False
        self._closed = False
        self._iter_consumed = False

        self._record: dict[str, Any] | None = None
        self._raw_journal_bytes: bytes | None = None
        self._jname: str | None = None
        self._cname: str | None = None

        self._root_sig: tuple[int, ...] | None = None
        self._journal_sig: tuple[int, ...] | None = None
        self._cipher_sig: tuple[int, ...] | None = None
        self._expected_size = 0
        self._expected_sha = ""

        try:
            if self._cancel_event is not None and type(self._cancel_event) is not threading.Event:
                _hold()
            self._check_time_and_cancel()

            if (
                type(expected_identity) is not tuple
                or len(expected_identity) != 4
                or any(type(x) is not int or isinstance(x, bool) for x in expected_identity)
            ):
                _hold()
            exp_dev, exp_ino, exp_uid, exp_mode = expected_identity
            if exp_dev <= 0 or exp_ino <= 0 or exp_uid < 0 or exp_mode != 0o700 or exp_uid != os.geteuid():
                _hold()
            self._expected_identity = (exp_dev, exp_ino, exp_uid, exp_mode)

            self._validated_payload = validate_checkpoint(trusted_context, payload)
            self._validated_context = copy.deepcopy(trusted_context)
            self._job_id = self._validated_payload["job_id"]
            self._request_digest = self._validated_payload["request_digest"]
            self._jname = f"sg-job-{self._job_id}.json"
            self._cname = f"sg-encrypted-{self._job_id}.bin"

            self._check_time_and_cancel()
            self._root_path = _validate_root_path(root, self._deadline, self._cancel_event)
            self._check_time_and_cancel()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

    def _check_time_and_cancel(self) -> None:
        if time.monotonic() >= self._deadline:
            _hold()
        if self._cancel_event is not None and self._cancel_event.is_set():
            _hold()

    def _verify_root(self) -> None:
        self._check_time_and_cancel()
        if self._root_fd is None:
            _hold()
        try:
            st_fd = os.fstat(self._root_fd)
            st_named = os.lstat(self._root_path)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

        exp_dev, exp_ino, exp_uid, _ = self._expected_identity
        if not stat.S_ISDIR(st_fd.st_mode) or (st_fd.st_mode & 0o7000) != 0 or stat.S_IMODE(st_fd.st_mode) != 0o700:
            _hold()
        if st_fd.st_dev != exp_dev or st_fd.st_ino != exp_ino or st_fd.st_uid != exp_uid:
            _hold()
        if _stat_sig(st_fd) != _stat_sig(st_named):
            _hold()
        if self._root_sig is not None and _stat_sig(st_fd) != self._root_sig:
            _hold()
        if os.path.realpath(self._root_path) != self._root_path:
            _hold()
        self._check_time_and_cancel()

    def _verify_journal(self) -> None:
        self._check_time_and_cancel()
        if self._root_fd is None or self._raw_journal_bytes is None or self._journal_sig is None or self._jname is None:
            _hold()
        try:
            jfd = os.open(self._jname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self._root_fd)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        try:
            st_jfd1 = os.fstat(jfd)
            named_j = os.lstat(self._jname, dir_fd=self._root_fd)
            if _stat_sig(st_jfd1) != self._journal_sig or _stat_sig(named_j) != self._journal_sig:
                _hold()
            if not stat.S_ISREG(st_jfd1.st_mode) or (st_jfd1.st_mode & 0o7000) != 0 or stat.S_IMODE(st_jfd1.st_mode) != 0o600:
                _hold()
            exp_dev, _, exp_uid, _ = self._expected_identity
            if st_jfd1.st_dev != exp_dev or st_jfd1.st_uid != exp_uid or st_jfd1.st_nlink != 1:
                _hold()
            if st_jfd1.st_size > _MAX_JOURNAL_SIZE or st_jfd1.st_size != len(self._raw_journal_bytes):
                _hold()
            raw = b""
            while True:
                self._check_time_and_cancel()
                chunk = os.read(jfd, 2049)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > _MAX_JOURNAL_SIZE:
                    _hold()
            if raw != self._raw_journal_bytes:
                _hold()
            st_jfd2 = os.fstat(jfd)
            named_final = os.lstat(self._jname, dir_fd=self._root_fd)
            if (_stat_sig(st_jfd1) != _stat_sig(st_jfd2)
                    or _stat_sig(named_final) != self._journal_sig):
                _hold()
        finally:
            try:
                os.close(jfd)
            except Exception:
                pass
        self._check_time_and_cancel()

    def _verify_cipher_descriptor_and_named(self) -> None:
        self._check_time_and_cancel()
        if self._root_fd is None or self._cipher_fd is None or self._cipher_sig is None or self._cname is None:
            _hold()
        try:
            st_cfd = os.fstat(self._cipher_fd)
            st_cnamed = os.lstat(self._cname, dir_fd=self._root_fd)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if _stat_sig(st_cfd) != self._cipher_sig or _stat_sig(st_cnamed) != self._cipher_sig:
            _hold()
        if not stat.S_ISREG(st_cfd.st_mode) or (st_cfd.st_mode & 0o7000) != 0 or stat.S_IMODE(st_cfd.st_mode) != 0o600:
            _hold()
        exp_dev, _, exp_uid, _ = self._expected_identity
        if st_cfd.st_dev != exp_dev or st_cfd.st_uid != exp_uid or st_cfd.st_nlink != 1:
            _hold()
        if st_cfd.st_size != self._expected_size:
            _hold()
        self._check_time_and_cancel()

    def __enter__(self) -> CheckpointExportReader:
        if self._entered or self._closed:
            _hold()
        self._entered = True
        self._check_time_and_cancel()

        try:
            root_flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            try:
                self._root_fd = os.open(self._root_path, root_flags)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()

            self._check_time_and_cancel()
            st_root = os.fstat(self._root_fd)
            exp_dev, exp_ino, exp_uid, _ = self._expected_identity
            if not stat.S_ISDIR(st_root.st_mode) or (st_root.st_mode & 0o7000) != 0 or stat.S_IMODE(st_root.st_mode) != 0o700:
                _hold()
            if st_root.st_dev != exp_dev or st_root.st_ino != exp_ino or st_root.st_uid != exp_uid:
                _hold()

            try:
                fcntl.flock(self._root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()

            self._root_sig = _stat_sig(st_root)
            self._verify_root()

            try:
                jfd = os.open(self._jname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self._root_fd)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()
            try:
                st_j1 = os.fstat(jfd)
                if not stat.S_ISREG(st_j1.st_mode) or (st_j1.st_mode & 0o7000) != 0 or stat.S_IMODE(st_j1.st_mode) != 0o600:
                    _hold()
                if st_j1.st_dev != exp_dev or st_j1.st_uid != exp_uid or st_j1.st_nlink != 1:
                    _hold()
                if st_j1.st_size > _MAX_JOURNAL_SIZE or st_j1.st_size <= 0:
                    _hold()
                raw_j = b""
                while True:
                    self._check_time_and_cancel()
                    chunk = os.read(jfd, 2049)
                    if not chunk:
                        break
                    raw_j += chunk
                    if len(raw_j) > _MAX_JOURNAL_SIZE:
                        _hold()
                if len(raw_j) != st_j1.st_size:
                    _hold()
                st_j2 = os.fstat(jfd)
                st_j_named = os.lstat(self._jname, dir_fd=self._root_fd)
                if _stat_sig(st_j1) != _stat_sig(st_j2) or _stat_sig(st_j1) != _stat_sig(st_j_named):
                    _hold()
                self._journal_sig = _stat_sig(st_j1)
                self._raw_journal_bytes = raw_j
            finally:
                try:
                    os.close(jfd)
                except Exception:
                    pass

            self._record = _parse_and_validate_record(self._raw_journal_bytes)
            if self._record["job_id"] != self._job_id or self._record["request_digest"] != self._request_digest:
                _hold()
            if self._record["state"] != "artifact-verified":
                _hold()
            art = self._record["artifact"]
            if not isinstance(art, dict) or art.get("leaf") != self._cname:
                _hold()
            self._expected_size = art["bytes"]
            self._expected_sha = art["sha256"]
            if not (1 <= self._expected_size <= _MAX_CIPHERTEXT_SIZE):
                _hold()

            try:
                self._cipher_fd = os.open(self._cname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self._root_fd)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()

            st_c1 = os.fstat(self._cipher_fd)
            if not stat.S_ISREG(st_c1.st_mode) or (st_c1.st_mode & 0o7000) != 0 or stat.S_IMODE(st_c1.st_mode) != 0o600:
                _hold()
            if st_c1.st_dev != exp_dev or st_c1.st_uid != exp_uid or st_c1.st_nlink != 1:
                _hold()
            if st_c1.st_size != self._expected_size:
                _hold()
            st_c_named = os.lstat(self._cname, dir_fd=self._root_fd)
            if _stat_sig(st_c1) != _stat_sig(st_c_named):
                _hold()
            self._cipher_sig = _stat_sig(st_c1)

            hasher = hashlib.sha256()
            total_read = 0
            while True:
                self._check_time_and_cancel()
                chunk = os.read(self._cipher_fd, _CHUNK_SIZE)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > self._expected_size:
                    _hold()
                hasher.update(chunk)
            if total_read != self._expected_size or hasher.hexdigest() != self._expected_sha:
                _hold()

            self._verify_cipher_descriptor_and_named()
            self._verify_journal()
            self._verify_root()

            try:
                os.lseek(self._cipher_fd, 0, os.SEEK_SET)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                _hold()

            self._check_time_and_cancel()
            return self
        except (KeyboardInterrupt, SystemExit):
            self.close()
            raise
        except Exception:
            self.close()
            _hold()

    def manifest(self) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            if not self._entered or self._closed:
                _hold()
            self._check_time_and_cancel()
            self._verify_cipher_descriptor_and_named()
            self._verify_journal()
            self._verify_root()
            self._check_time_and_cancel()
            return copy.deepcopy(self._validated_context), copy.deepcopy(self._record)
        except (KeyboardInterrupt, SystemExit):
            self.close()
            raise
        except Exception:
            self.close()
            _hold()

    def iter_chunks(self) -> Generator[bytes, None, None]:
        if not self._entered or self._closed or self._iter_consumed:
            _hold()
        self._iter_consumed = True

        hasher = hashlib.sha256()
        bytes_yielded = 0
        expected_len = self._expected_size

        try:
            while True:
                self._check_time_and_cancel()
                if self._closed or self._cipher_fd is None:
                    _hold()
                self._verify_cipher_descriptor_and_named()
                self._verify_root()
                self._check_time_and_cancel()

                read_limit = min(_CHUNK_SIZE, expected_len - bytes_yielded)
                if read_limit == 0:
                    break

                try:
                    chunk = os.read(self._cipher_fd, read_limit)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    _hold()

                if not chunk:
                    _hold()

                hasher.update(chunk)
                bytes_after_chunk = bytes_yielded + len(chunk)

                if bytes_after_chunk < expected_len:
                    bytes_yielded = bytes_after_chunk
                    self._check_time_and_cancel()
                    yield chunk
                else:
                    if bytes_after_chunk != expected_len:
                        _hold()

                    try:
                        probe = os.read(self._cipher_fd, 1)
                    except (KeyboardInterrupt, SystemExit):
                        raise
                    except Exception:
                        _hold()
                    if len(probe) != 0:
                        _hold()

                    if hasher.hexdigest() != self._expected_sha:
                        _hold()

                    self._verify_cipher_descriptor_and_named()
                    self._verify_journal()
                    self._verify_root()
                    _validate_root_path(self._root_path, self._deadline, self._cancel_event)
                    self._check_time_and_cancel()

                    bytes_yielded = bytes_after_chunk
                    self._check_time_and_cancel()
                    yield chunk
                    break
        except (KeyboardInterrupt, SystemExit):
            self.close()
            raise
        except Exception:
            self.close()
            _hold()
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._cipher_fd is not None:
            try:
                os.close(self._cipher_fd)
            except Exception:
                pass
            self._cipher_fd = None
        if self._root_fd is not None:
            try:
                fcntl.flock(self._root_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(self._root_fd)
            except Exception:
                pass
            self._root_fd = None

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

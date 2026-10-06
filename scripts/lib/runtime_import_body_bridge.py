"""Standalone import body bridge for secure incremental streaming and verification."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import math
import os
import select
import socket
import stat
import threading
import time
from typing import Any

__all__ = ["ImportBodyBridge"]

_MAX_ALLOWED_BYTES = 64 * 1024 * 1024 + 4136
_CHUNK_SIZE = 64 * 1024
_HELD_MSG = "Import body bridge held"


def _held_exc() -> RuntimeError:
    return RuntimeError(_HELD_MSG)


def _is_hex_sha256(s: Any) -> bool:
    if type(s) is not str or len(s) != 64:
        return False
    for ch in s:
        if ch not in "0123456789abcdef":
            return False
    return True


def _safe_fstat(fd: int | None) -> tuple[int, int, int] | None:
    if fd is None or type(fd) is not int or fd < 0:
        return None
    try:
        st = os.fstat(fd)
        return (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode))
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return None


def _close_fd_no_retry(fd: int | None) -> bool:
    if fd is None or type(fd) is not int or fd < 0:
        return True
    try:
        os.close(fd)
        return True
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return False


class ImportBodyBridge:
    """Transfers and verifies HTTP body chunks via an incremental pipe bridge."""

    def __init__(
        self,
        connection: socket.socket,
        expected_bytes: int,
        expected_sha256: str,
        cancel_event: threading.Event,
        deadline: float,
    ) -> None:
        try:
            if (
                type(expected_bytes) is not int
                or isinstance(expected_bytes, bool)
                or expected_bytes < 1
                or expected_bytes > _MAX_ALLOWED_BYTES
            ):
                raise _held_exc() from None

            if not _is_hex_sha256(expected_sha256):
                raise _held_exc() from None

            if (
                not isinstance(cancel_event, threading.Event)
                or type(cancel_event) is not threading.Event
            ):
                raise _held_exc() from None

            if (
                type(deadline) not in (int, float)
                or isinstance(deadline, bool)
                or not math.isfinite(deadline)
            ):
                raise _held_exc() from None

            dl = float(deadline)
            now_mono = time.monotonic()
            if not (now_mono < dl <= now_mono + 15.0):
                raise _held_exc() from None

            if (
                not isinstance(connection, socket.socket)
                or type(connection) is not socket.socket
            ):
                raise _held_exc() from None

            sock_type = connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            if sock_type != socket.SOCK_STREAM:
                raise _held_exc() from None
            connection.getpeername()
            orig_fd = connection.fileno()
            if orig_fd < 0:
                raise _held_exc() from None
            orig_stat = _safe_fstat(orig_fd)
            if orig_stat is None:
                raise _held_exc() from None
            orig_flags = fcntl.fcntl(orig_fd, fcntl.F_GETFL)
            orig_timeout = connection.gettimeout()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise _held_exc() from None

        self._conn = connection
        self._orig_fd = orig_fd
        self._orig_stat = orig_stat
        self._orig_flags = orig_flags
        self._orig_timeout = orig_timeout
        self._expected_bytes = expected_bytes
        self._expected_sha256 = expected_sha256
        self._cancel_event = cancel_event
        self._deadline = dl

        self._pipe_r: int | None = None
        self._pipe_r_stat: tuple[int, int, int] | None = None
        self._pipe_w: int | None = None
        self._pipe_w_stat: tuple[int, int, int] | None = None
        self._sock_dup_fd: int | None = None
        self._sock_dup_stat: tuple[int, int, int] | None = None

        self._started = False
        self._finished = False
        self._aborted = False
        self._fault = False
        self._cleanup_fault = False
        self._worker_thread: threading.Thread | None = None
        self._worker_started = False
        self._worker_quiescent = True
        self._replay_requested = False
        self._replay_discarded = False
        self._producer_error: Exception | None = None
        try:
            self._producer_done = threading.Event()
            self._bytes_hashed = 0
            self._sha256_matched = False
            self._writer_closed_ok: bool | None = None
            self._dup_closed_ok: bool | None = None
            self._lock = threading.Lock()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise _held_exc() from None

    @property
    def worker_quiescent(self) -> bool:
        try:
            with self._lock:
                started = self._worker_started
                worker = self._worker_thread
                explicit_quiescent = self._worker_quiescent
            if started and worker is not None:
                try:
                    if worker.is_alive():
                        return False
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    return False
            return explicit_quiescent
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return False

    def start(self) -> int:
        with self._lock:
            if self._started or self._finished or self._aborted or self._fault:
                raise _held_exc() from None
            try:
                if self._cancel_event.is_set() or time.monotonic() >= self._deadline:
                    self._fault = True
                    raise _held_exc() from None
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                self._fault = True
                raise _held_exc() from None

            cur_stat = _safe_fstat(self._orig_fd)
            if cur_stat is None or cur_stat != self._orig_stat:
                self._fault = True
                raise _held_exc() from None

            pipe_r = -1
            pipe_w = -1
            dup_fd = -1
            pipe_r_stat = None
            pipe_w_stat = None
            dup_stat = None
            try:
                if hasattr(os, "pipe2") and hasattr(os, "O_NONBLOCK") and hasattr(os, "O_CLOEXEC"):
                    pipe_r, pipe_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)  # type: ignore[attr-defined]
                    pipe_r_stat = _safe_fstat(pipe_r)
                    pipe_w_stat = _safe_fstat(pipe_w)
                else:
                    pipe_r, pipe_w = os.pipe()
                    pipe_r_stat = _safe_fstat(pipe_r)
                    pipe_w_stat = _safe_fstat(pipe_w)
                    for pfd in (pipe_r, pipe_w):
                        flags = fcntl.fcntl(pfd, fcntl.F_GETFL)
                        fcntl.fcntl(pfd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                        fcntl.fcntl(pfd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)

                dup_fd = os.dup(self._orig_fd)
                dup_stat = _safe_fstat(dup_fd)
                if dup_stat != self._orig_stat or _safe_fstat(self._orig_fd) != self._orig_stat:
                    raise _held_exc() from None
                fcntl.fcntl(dup_fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
                dflags = fcntl.fcntl(dup_fd, fcntl.F_GETFL)
                fcntl.fcntl(dup_fd, fcntl.F_SETFL, dflags | os.O_NONBLOCK)

                if not (pipe_r_stat and pipe_w_stat and dup_stat):
                    raise RuntimeError("FD stat failure")

                self._pipe_r = pipe_r
                self._pipe_r_stat = pipe_r_stat
                self._pipe_w = pipe_w
                self._pipe_w_stat = pipe_w_stat
                self._sock_dup_fd = dup_fd
                self._sock_dup_stat = dup_stat

                worker = threading.Thread(target=self._producer_loop, daemon=False)
                self._worker_thread = worker
                self._worker_quiescent = False
                self._started = True
            except (KeyboardInterrupt, SystemExit):
                self._fault = True
                c_ok = True
                if pipe_r >= 0 and _safe_fstat(pipe_r) == pipe_r_stat:
                    if not _close_fd_no_retry(pipe_r):
                        c_ok = False
                elif pipe_r >= 0:
                    c_ok = False

                if pipe_w >= 0 and _safe_fstat(pipe_w) == pipe_w_stat:
                    if not _close_fd_no_retry(pipe_w):
                        c_ok = False
                elif pipe_w >= 0:
                    c_ok = False

                if dup_fd >= 0 and _safe_fstat(dup_fd) == dup_stat:
                    if not _close_fd_no_retry(dup_fd):
                        c_ok = False
                elif dup_fd >= 0:
                    c_ok = False

                self._pipe_r = self._pipe_w = self._sock_dup_fd = None
                if not self._restore_socket_flags() or not c_ok:
                    self._cleanup_fault = True
                self._worker_quiescent = True
                raise
            except Exception:
                self._fault = True
                c_ok = True
                if pipe_r >= 0 and _safe_fstat(pipe_r) == pipe_r_stat:
                    if not _close_fd_no_retry(pipe_r):
                        c_ok = False
                elif pipe_r >= 0:
                    c_ok = False

                if pipe_w >= 0 and _safe_fstat(pipe_w) == pipe_w_stat:
                    if not _close_fd_no_retry(pipe_w):
                        c_ok = False
                elif pipe_w >= 0:
                    c_ok = False

                if dup_fd >= 0 and _safe_fstat(dup_fd) == dup_stat:
                    if not _close_fd_no_retry(dup_fd):
                        c_ok = False
                elif dup_fd >= 0:
                    c_ok = False

                self._pipe_r = self._pipe_w = self._sock_dup_fd = None
                if not self._restore_socket_flags() or not c_ok:
                    self._cleanup_fault = True
                self._worker_quiescent = True
                raise _held_exc() from None

        thread_launched = False
        try:
            worker.start()
            thread_launched = True
            with self._lock:
                self._worker_started = True
        except (KeyboardInterrupt, SystemExit):
            try:
                self._reconcile_and_contain_failed_start(worker, thread_launched)
            except BaseException:
                pass
            raise
        except Exception:
            try:
                self._reconcile_and_contain_failed_start(worker, thread_launched)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            raise _held_exc() from None

        return pipe_r

    def _reconcile_and_contain_failed_start(self, worker: threading.Thread, thread_launched: bool) -> None:
        with self._lock:
            self._fault = True
            is_alive = False
            launch_unknown = False
            try:
                is_alive = worker.is_alive() or getattr(worker, "ident", None) is not None
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                launch_unknown = True
                self._cleanup_fault = True
            if thread_launched or is_alive or launch_unknown:
                self._worker_started = True
            else:
                self._worker_started = False
                self._worker_quiescent = True
                c_ok = True
                if self._pipe_w is not None and _safe_fstat(self._pipe_w) == self._pipe_w_stat:
                    if not _close_fd_no_retry(self._pipe_w):
                        c_ok = False
                elif self._pipe_w is not None:
                    c_ok = False

                if self._sock_dup_fd is not None and _safe_fstat(self._sock_dup_fd) == self._sock_dup_stat:
                    if not _close_fd_no_retry(self._sock_dup_fd):
                        c_ok = False
                elif self._sock_dup_fd is not None:
                    c_ok = False

                self._pipe_w = None
                self._sock_dup_fd = None
                self._writer_closed_ok = c_ok
                self._dup_closed_ok = c_ok
                if not c_ok:
                    self._cleanup_fault = True

        try:
            self._cancel_event.set()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            pass
        self._contained_cleanup(allowance=1.0)

    def _producer_loop(self) -> None:
        dup_fd = None
        pipe_w = None
        dup_stat = None
        pipe_w_stat = None
        try:
            with self._lock:
                dup_fd = self._sock_dup_fd
                pipe_w = self._pipe_w
                dup_stat = self._sock_dup_stat
                pipe_w_stat = self._pipe_w_stat

            hasher = hashlib.sha256()
            remaining = self._expected_bytes
            discard_active = False

            if (
                dup_fd is None
                or pipe_w is None
                or _safe_fstat(dup_fd) != dup_stat
                or _safe_fstat(pipe_w) != pipe_w_stat
            ):
                raise RuntimeError("FD verification failed at worker entry")

            while remaining > 0:
                if self._cancel_event.is_set() or time.monotonic() >= self._deadline:
                    raise RuntimeError("Cancelled or deadline exceeded")

                with self._lock:
                    if self._replay_requested:
                        discard_active = True

                to_read = min(_CHUNK_SIZE, remaining)
                try:
                    r_ready, _, _ = select.select([dup_fd], [], [], 0.05)
                except (select.error, OSError) as e:
                    if getattr(e, "errno", None) == errno.EINTR:
                        continue
                    raise

                if not r_ready:
                    continue

                if _safe_fstat(dup_fd) != dup_stat:
                    raise RuntimeError("Socket dup descriptor altered")

                try:
                    chunk = os.read(dup_fd, to_read)
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError as e:
                    if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                        continue
                    raise

                if not chunk:
                    raise RuntimeError("Early EOF from socket")

                hasher.update(chunk)
                with self._lock:
                    self._bytes_hashed += len(chunk)
                remaining -= len(chunk)

                if not discard_active:
                    with self._lock:
                        if self._replay_requested:
                            discard_active = True

                if discard_active:
                    with self._lock:
                        self._replay_discarded = True
                else:
                    offset = 0
                    chunk_len = len(chunk)
                    while offset < chunk_len:
                        if self._cancel_event.is_set() or time.monotonic() >= self._deadline:
                            raise RuntimeError("Cancelled or deadline exceeded during write")
                        with self._lock:
                            if self._replay_requested:
                                discard_active = True
                                self._replay_discarded = True
                                break

                        try:
                            _, w_ready, _ = select.select([], [pipe_w], [], 0.05)
                        except (select.error, OSError) as e:
                            if getattr(e, "errno", None) == errno.EINTR:
                                continue
                            raise

                        if not w_ready:
                            continue

                        if _safe_fstat(pipe_w) != pipe_w_stat:
                            raise RuntimeError("Pipe writer descriptor altered")

                        try:
                            written = os.write(pipe_w, memoryview(chunk)[offset:])
                            if written == 0:
                                raise RuntimeError("Zero progress write")
                            if written > 0:
                                offset += written
                        except (BlockingIOError, InterruptedError):
                            continue
                        except OSError as e:
                            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                                continue
                            raise

            # Finished exact byte count. Check digest and queued trailing bytes.
            digest = hasher.hexdigest()
            if digest != self._expected_sha256:
                raise RuntimeError("SHA256 mismatch")
            with self._lock:
                self._sha256_matched = True

            try:
                r_ready, _, _ = select.select([dup_fd], [], [], 0.0)
                if r_ready:
                    if _safe_fstat(dup_fd) != dup_stat:
                        raise RuntimeError("Socket dup altered during trailer check")
                    try:
                        probe = os.read(dup_fd, 1)
                        if len(probe) > 0:
                            raise RuntimeError("Unexpected queued trailer bytes")
                    except (BlockingIOError, InterruptedError):
                        pass
                    except OSError as e:
                        if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                            raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException:
                raise

        except (KeyboardInterrupt, SystemExit):
            with self._lock:
                self._producer_error = RuntimeError("Interrupt")
                self._fault = True
            try:
                self._cancel_event.set()
            except BaseException:
                pass
        except Exception as exc:
            with self._lock:
                self._producer_error = exc
                self._fault = True
            try:
                self._cancel_event.set()
            except BaseException:
                pass
        finally:
            w_ok = False
            d_ok = False
            try:
                if pipe_w is not None and _safe_fstat(pipe_w) == pipe_w_stat:
                    w_ok = _close_fd_no_retry(pipe_w)
                elif pipe_w is None:
                    w_ok = True
            except BaseException:
                w_ok = False

            try:
                if dup_fd is not None and _safe_fstat(dup_fd) == dup_stat:
                    d_ok = _close_fd_no_retry(dup_fd)
                elif dup_fd is None:
                    d_ok = True
            except BaseException:
                d_ok = False

            with self._lock:
                self._pipe_w = None
                self._sock_dup_fd = None
                self._writer_closed_ok = w_ok
                self._dup_closed_ok = d_ok
                if not w_ok or not d_ok:
                    self._fault = True
                    self._cleanup_fault = True
            try:
                self._producer_done.set()
            except BaseException:
                with self._lock:
                    self._fault = True

    def _restore_socket_flags(self) -> bool:
        try:
            if _safe_fstat(self._orig_fd) != self._orig_stat:
                return False
            self._conn.settimeout(self._orig_timeout)
            fcntl.fcntl(self._orig_fd, fcntl.F_SETFL, self._orig_flags)
            cur_flags = fcntl.fcntl(self._orig_fd, fcntl.F_GETFL)
            cur_timeout = self._conn.gettimeout()
            if cur_flags != self._orig_flags or cur_timeout != self._orig_timeout:
                return False
            if _safe_fstat(self._orig_fd) != self._orig_stat:
                return False
            return True
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return False

    def _contained_cleanup(self, allowance: float = 1.0, end_deadline: float | None = None) -> None:
        try:
            if end_deadline is not None:
                end_time = float(end_deadline)
            else:
                end_time = time.monotonic() + max(0.0, float(allowance))
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            end_time = time.monotonic() + 1.0

        with self._lock:
            worker = self._worker_thread
            worker_started = self._worker_started

        if worker_started and worker is not None:
            try:
                if worker.is_alive():
                    rem = max(0.001, end_time - time.monotonic())
                    worker.join(timeout=rem)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                with self._lock:
                    self._fault = True
                    self._cleanup_fault = True

        with self._lock:
            worker_alive = False
            if worker_started and worker is not None:
                try:
                    worker_alive = worker.is_alive()
                except Exception:
                    worker_alive = True

            if worker_alive:
                self._worker_quiescent = False
                self._fault = True
                self._cleanup_fault = True
                return
            self._worker_quiescent = True

            pipe_r = self._pipe_r
            pipe_r_stat = self._pipe_r_stat
            self._pipe_r = None

        if pipe_r is not None:
            if _safe_fstat(pipe_r) == pipe_r_stat:
                if not _close_fd_no_retry(pipe_r):
                    with self._lock:
                        self._fault = True
                        self._cleanup_fault = True
            else:
                with self._lock:
                    self._fault = True
                    self._cleanup_fault = True

        restored = self._restore_socket_flags()
        if not restored:
            with self._lock:
                self._fault = True
                self._cleanup_fault = True

    def finish(self, *, verified_replay: bool = False) -> dict[str, Any]:
        if type(verified_replay) is not bool:
            self.abort()
            raise _held_exc() from None

        with self._lock:
            if not self._started or self._finished or self._aborted:
                raise _held_exc() from None
            self._finished = True
            if verified_replay:
                self._replay_requested = True
            worker = self._worker_thread
            worker_started = self._worker_started

        if not worker_started or worker is None:
            self.abort()
            raise _held_exc() from None

        try:
            cleanup_deadline = time.monotonic() + 1.0
            remaining_budget = self._deadline - time.monotonic()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            # A failed clock cannot supply a new budget. Retain the caller's bound.
            cleanup_deadline = self._deadline + 1.0
            remaining_budget = -1.0

        if remaining_budget <= 0.0:
            try:
                self._cancel_event.set()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            try:
                self._contained_cleanup(end_deadline=cleanup_deadline)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            raise _held_exc() from None

        join_error = False
        try:
            worker.join(timeout=remaining_budget)
        except (KeyboardInterrupt, SystemExit):
            try:
                self._contained_cleanup(end_deadline=cleanup_deadline)
            except BaseException:
                pass
            raise
        except Exception:
            join_error = True
            with self._lock:
                self._fault = True
                self._cleanup_fault = True

        if join_error:
            try:
                self._cancel_event.set()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            try:
                self._contained_cleanup(end_deadline=cleanup_deadline)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            raise _held_exc() from None

        worker_still_alive = False
        try:
            worker_still_alive = worker.is_alive()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            worker_still_alive = True

        if worker_still_alive:
            try:
                self._cancel_event.set()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            try:
                self._contained_cleanup(end_deadline=cleanup_deadline)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
            raise _held_exc() from None

        try:
            self._contained_cleanup(end_deadline=cleanup_deadline)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            with self._lock:
                self._fault = True
                self._cleanup_fault = True

        with self._lock:
            self._worker_quiescent = True
            w_ok = self._writer_closed_ok
            d_ok = self._dup_closed_ok
            producer_err = self._producer_error
            sha_matched = self._sha256_matched
            bytes_hashed = self._bytes_hashed
            replay_disc = self._replay_discarded
            cleanup_fault = self._cleanup_fault
            fault = self._fault

        try:
            event_set = self._cancel_event.is_set()
            over_deadline = time.monotonic() > self._deadline
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            event_set = True
            over_deadline = True

        if (
            cleanup_fault
            or fault
            or w_ok is not True
            or d_ok is not True
            or producer_err is not None
            or not sha_matched
            or bytes_hashed != self._expected_bytes
            or event_set
            or over_deadline
        ):
            with self._lock:
                self._fault = True
            raise _held_exc() from None

        return {
            "schema": "sg.local-import-body-bridge.v1",
            "state": "body-verified",
            "bytes": self._expected_bytes,
            "sha256": self._expected_sha256,
            "replay_discard": bool(replay_disc),
        }

    def abort(self) -> None:
        ki_or_se = None
        try:
            try:
                self._cancel_event.set()
            except (KeyboardInterrupt, SystemExit) as c_exc:
                ki_or_se = c_exc
            except Exception:
                pass
            with self._lock:
                self._aborted = True
                self._fault = True
            try:
                self._contained_cleanup(allowance=1.0)
            except (KeyboardInterrupt, SystemExit) as c_exc:
                if ki_or_se is None:
                    ki_or_se = c_exc
            except Exception:
                with self._lock:
                    self._fault = True
                    self._cleanup_fault = True
            with self._lock:
                if self._cleanup_fault:
                    raise _held_exc() from None
        except (KeyboardInterrupt, SystemExit) as exc:
            if ki_or_se is None:
                ki_or_se = exc
        except Exception as exc:
            if ki_or_se is None:
                raise _held_exc() from None

        if ki_or_se is not None:
            raise ki_or_se

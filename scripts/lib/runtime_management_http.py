"""Authenticated local management HTTP listener with OperationGate concurrency control."""
from __future__ import annotations

import copy
import fcntl
import hmac
import json
import math
import os
import re
import select
import socket
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime_cipher_export import CheckpointExportReader

try:
    from .runtime_job_journal import _parse_and_validate_record, _serialize_record
    from .runtime_operation_identity import checkpoint_digest, validate_checkpoint, validate_restore
    from .runtime_import_http_contract import parse_import_headers, validate_import_result
    from .runtime_import_body_bridge import ImportBodyBridge
    from .runtime_import_request_registry import ImportRequestRegistry
except ImportError:
    from lib.runtime_job_journal import _parse_and_validate_record, _serialize_record
    from lib.runtime_operation_identity import checkpoint_digest, validate_checkpoint, validate_restore
    from lib.runtime_import_http_contract import parse_import_headers, validate_import_result
    from lib.runtime_import_body_bridge import ImportBodyBridge
    from lib.runtime_import_request_registry import ImportRequestRegistry

KEY_RE = re.compile(r"^[A-Za-z0-9._~-]{32,256}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
LEAF_RE = re.compile(r"^sg-encrypted-[0-9a-f]{32}\.bin$")
MAX_RESTORE_BYTES = 64 * 1024 * 1024 + 4136
MAX_CIPHER_BYTES = 64 * 1024 * 1024 + 4136


def _safe_fstat_local(fd: int | None) -> tuple[int, int, int] | None:
    if fd is None or type(fd) is not int or fd < 0:
        return None
    try:
        st = os.fstat(fd)
        return (st.st_dev, st.st_ino, stat.S_IFMT(st.st_mode))
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return None


def _close_fd_no_retry_local(fd: int | None) -> bool:
    if fd is None or type(fd) is not int or fd < 0:
        return True
    try:
        os.close(fd)
        return True
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return False


class OperationGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_tokens: set[object] = set()
        self._mutating = False
        self._closing = False
        self._idle_notification = threading.Event()
        self._idle_notification.set()

    def close_admission(self) -> None:
        acquired = self._lock.acquire(timeout=1.0)
        if not acquired:
            raise RuntimeError("OperationGate lock held")
        try:
            self._closing = True
        finally:
            self._lock.release()

    def wait_idle(self, timeout: int | float) -> bool:
        if type(timeout) not in (int, float) or not 0 < timeout <= 60 or not math.isfinite(timeout):
            raise ValueError("Invalid timeout for wait_idle")
        deadline = time.monotonic() + float(timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            acquired = self._lock.acquire(timeout=min(remaining, 0.1))
            if acquired:
                try:
                    is_idle = (not self._mutating) and (len(self._active_tokens) == 0)
                    now = time.monotonic()
                    if is_idle:
                        return now < deadline
                    if now >= deadline:
                        return False
                finally:
                    self._lock.release()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._idle_notification.wait(timeout=min(remaining, 0.1))
            if time.monotonic() >= deadline:
                return False

    def begin_stream(self) -> object:
        with self._lock:
            if self._closing:
                raise RuntimeError("Gate admission closed")
            if self._mutating:
                raise RuntimeError("Mutation in progress")
            token = object()
            self._active_tokens.add(token)
            self._idle_notification.clear()
            return token

    def end_stream(self, token: object) -> None:
        with self._lock:
            if token not in self._active_tokens:
                raise RuntimeError("Invalid stream token")
            self._active_tokens.remove(token)
            if len(self._active_tokens) == 0 and not self._mutating:
                self._idle_notification.set()

    def begin_mutation(self) -> None:
        with self._lock:
            if self._closing:
                raise RuntimeError("Gate admission closed")
            if self._mutating or len(self._active_tokens) > 0:
                raise RuntimeError("Cannot begin mutation: active operations present")
            self._mutating = True
            self._idle_notification.clear()

    def end_mutation(self) -> None:
        with self._lock:
            if not self._mutating:
                raise RuntimeError("No mutation in progress")
            self._mutating = False
            if len(self._active_tokens) == 0:
                self._idle_notification.set()


class _BoundedHeaderReader:
    def __init__(self, raw: Any, connection: socket.socket, deadline: float, limit: int = 32768) -> None:
        self.raw = raw
        self.connection = connection
        self.deadline = deadline
        self.remaining = limit

    def readline(self, size: int = -1) -> bytes:
        out = bytearray()
        while size < 0 or len(out) < size:
            if self.remaining <= 0:
                raise ValueError("Header limit")
            remaining_time = self.deadline - time.monotonic()
            if remaining_time <= 0:
                raise TimeoutError("Header deadline")
            self.connection.settimeout(remaining_time)
            byte = self.raw.read(1)
            if not byte:
                break
            self.remaining -= 1
            out.extend(byte)
            if byte == b"\n":
                break
        return bytes(out)


class _ManagementServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type,
        checkpoint_cb: Callable[[dict[str, Any]], dict[str, Any]],
        restore_cb: Callable[[dict[str, Any]], dict[str, Any]],
        export_cb: Callable[[dict[str, Any]], CheckpointExportReader] | None,
        import_cb: Callable[..., dict[str, Any]] | None,
        import_request_registry: ImportRequestRegistry | None,
        management_key: str,
        max_conn: int,
        conn_timeout: float,
        gate: OperationGate,
        operation_context: dict[str, Any],
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.operation_context = operation_context
        self.checkpoint_cb = checkpoint_cb
        self.restore_cb = restore_cb
        self.export_cb = export_cb
        self.import_cb = import_cb
        self.import_request_registry = import_request_registry
        self.management_key = management_key
        self.conn_timeout = conn_timeout
        self.gate = gate
        self.conn_semaphore = threading.Semaphore(max_conn)

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.conn_semaphore.acquire(blocking=False):
            try:
                request.close()
            except Exception:
                pass
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.conn_semaphore.release()
            raise


class _ManagementHandler(BaseHTTPRequestHandler):
    rbufsize = 0

    def __getattr__(self, name: str) -> Any:
        if name.startswith("do_"):
            return self._handle_unsupported
        raise AttributeError(name)

    server: _ManagementServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        msg = "request held"
        self._send_response_raw(code, "text/plain; charset=utf-8", msg.encode("utf-8"))

    def _send_response_raw(self, status: int, content_type: str, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except Exception:
            pass
        finally:
            self.close_connection = True

    def handle(self) -> None:
        self._start_time = time.monotonic()
        self.connection.settimeout(self.server.conn_timeout)
        self.request_version = "HTTP/1.1"
        self.command = ""
        self.requestline = ""
        self._body_reader = self.rfile
        self.rfile = _BoundedHeaderReader(self.rfile, self.connection, self._start_time + self.server.conn_timeout)
        try:
            super().handle()
        except ValueError:
            self._send_response_raw(431, "text/plain", b"request held")
        except TimeoutError:
            self._send_response_raw(408, "text/plain", b"request held")
        except Exception:
            self._send_response_raw(400, "text/plain", b"request held")
        finally:
            self.rfile = self._body_reader
            self.server.conn_semaphore.release()

    def parse_request(self) -> bool:
        try:
            return super().parse_request()
        except ValueError:
            self._send_response_raw(431, "text/plain", b"request held")
            return False
        except TimeoutError:
            self._send_response_raw(408, "text/plain", b"request held")
            return False
        except Exception:
            self._send_response_raw(400, "text/plain", b"request held")
            return False
        finally:
            self.rfile = self._body_reader

    def _validate_auth(self) -> bool:
        auth_headers = self.headers.get_all("Authorization", [])
        if len(auth_headers) != 1:
            return False
        parts = auth_headers[0].split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer":
            return False
        token = parts[1]
        if not KEY_RE.fullmatch(token):
            return False
        return hmac.compare_digest(token.encode("ascii"), self.server.management_key.encode("ascii"))

    def _read_body(self) -> bytes | None:
        if "Transfer-Encoding" in self.headers or "Expect" in self.headers:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        cl_headers = self.headers.get_all("Content-Length", [])
        if len(cl_headers) != 1:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        cl_val = cl_headers[0]
        if not cl_val.isdigit() or cl_val.startswith("+") or cl_val.startswith("-"):
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        length = int(cl_val)
        if length < 1 or length > 2048 or str(length) != cl_val:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        ct_headers = self.headers.get_all("Content-Type", [])
        if len(ct_headers) != 1 or ct_headers[0].strip() != "application/json":
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None

        body = bytearray()
        sock = self.connection
        while len(body) < length:
            remaining_time = self.server.conn_timeout - (time.monotonic() - self._start_time)
            if remaining_time <= 0:
                self._send_response_raw(408, "text/plain; charset=utf-8", b"Request Timeout")
                return None
            r, _, _ = select.select([sock], [], [], min(remaining_time, 0.5))
            if not r:
                continue
            chunk = sock.recv(min(length - len(body), 4096))
            if not chunk:
                self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
                return None
            body.extend(chunk)

        r, _, _ = select.select([sock], [], [], 0.0)
        if r:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        return bytes(body)

    def _parse_and_validate_payload(self, is_restore: bool, raw_body: bytes) -> dict[str, Any] | None:
        try:
            text = raw_body.decode("utf-8")
            seen_keys: set[str] = set()

            def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                res = {}
                for k, v in pairs:
                    if k in seen_keys:
                        raise ValueError("Duplicate key")
                    seen_keys.add(k)
                    res[k] = v
                return res

            data = json.loads(
                text,
                object_pairs_hook=_pairs_hook,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid constant")),
            )
        except Exception:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None

        if not isinstance(data, dict):
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None

        try:
            validator = validate_restore if is_restore else validate_checkpoint
            return validator(self.server.operation_context, data)
        except ValueError:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None

    def _send_bounded_import_response(
        self,
        response_bytes: bytes,
        cancel_event: threading.Event,
        deadline: float,
    ) -> bool:
        sock = self.connection
        try:
            now = time.monotonic()
            if cancel_event.is_set() or not math.isfinite(now) or now >= deadline:
                return False
            rem = deadline - now
            if rem <= 0:
                return False
            sock.settimeout(rem)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            now = time.monotonic()
            if cancel_event.is_set() or not math.isfinite(now) or now >= deadline:
                return False
            rem = deadline - now
            if rem <= 0:
                return False
            sock.settimeout(rem)
            self.end_headers()

            view = memoryview(response_bytes)
            while len(view) > 0:
                now = time.monotonic()
                if cancel_event.is_set() or not math.isfinite(now) or now >= deadline:
                    return False
                rem = deadline - now
                if rem <= 0:
                    return False
                sock.settimeout(rem)
                to_send = view[: min(len(view), 4096)]
                nw = sock.send(to_send)
                if nw <= 0:
                    return False
                view = view[nw:]

            now = time.monotonic()
            if cancel_event.is_set() or not math.isfinite(now) or now >= deadline:
                return False
            rem = deadline - now
            if rem <= 0:
                return False
            sock.settimeout(rem)
            self.wfile.flush()
            now = time.monotonic()
            if cancel_event.is_set() or not math.isfinite(now) or now >= deadline:
                return False
            return True
        except Exception:
            return False
        finally:
            self.close_connection = True

    def _handle_import(self) -> None:
        if self.server.import_cb is None or self.server.import_request_registry is None:
            self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            return

        entry_now = time.monotonic()
        http_deadline = entry_now + 15.0

        try:
            raw_headers = list(self.headers.raw_items())
            validated_ctx, validated_rec, validated_rcpt = parse_import_headers(
                raw_headers,
                self.server.operation_context,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return

        now = time.monotonic()
        if now >= http_deadline:
            self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            return

        gate_held = False
        registry_registered = False
        reg_handle = None
        cancel_event = None
        bridge = None
        input_fd = -1
        orig_cb_exc = None
        success_response_bytes = None
        finish_succeeded = False
        cleanup_uncertain = False
        gate_end_attempted = False
        unregister_attempted = False

        try:
            self.server.gate.begin_mutation()
            gate_held = True
        except RuntimeError:
            self._send_response_raw(409, "text/plain; charset=utf-8", b"Conflict")
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            return

        try:
            try:
                reg_handle, cancel_event = self.server.import_request_registry.register()
                registry_registered = True
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            now = time.monotonic()
            if cancel_event.is_set() or now >= http_deadline:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            expected_bytes = validated_rec["artifact"]["bytes"]
            expected_sha256 = validated_rec["artifact"]["sha256"]
            try:
                bridge = ImportBodyBridge(
                    self.connection,
                    expected_bytes,
                    expected_sha256,
                    cancel_event,
                    http_deadline,
                )
                input_fd = bridge.start()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            cb_result = None
            try:
                ctx_copy1 = copy.deepcopy(validated_ctx)
                rec_copy1 = copy.deepcopy(validated_rec)
                rcpt_copy1 = copy.deepcopy(validated_rcpt)
                cb_result = self.server.import_cb(
                    ctx_copy1,
                    rec_copy1,
                    rcpt_copy1,
                    input_fd,
                    cancel_event,
                    http_deadline,
                )
            except (KeyboardInterrupt, SystemExit) as cbe:
                orig_cb_exc = cbe
                raise
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            validated_first_result = None
            try:
                validated_first_result = validate_import_result(
                    cb_result,
                    validated_ctx,
                    validated_rec,
                    validated_rcpt,
                )
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            initial_replay_stage = validated_first_result["replay_stage"]
            initial_replay_journal = validated_first_result["replay_journal"]
            do_replay = bool(initial_replay_stage)

            try:
                bridge_res = bridge.finish(verified_replay=do_replay)
                if not isinstance(bridge_res, dict) or bridge_res.get("state") != "body-verified":
                    raise RuntimeError("Bridge finish verification held")
                finish_succeeded = True
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if do_replay:
                replay_r = -1
                replay_w = -1
                replay_r_stat = None
                replay_w_stat = None
                replay_r_closed = False
                try:
                    if hasattr(os, "pipe2") and hasattr(os, "O_NONBLOCK") and hasattr(os, "O_CLOEXEC"):
                        replay_r, replay_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)  # type: ignore[attr-defined]
                        replay_r_stat = _safe_fstat_local(replay_r)
                        replay_w_stat = _safe_fstat_local(replay_w)
                    else:
                        replay_r, replay_w = os.pipe()
                        replay_r_stat = _safe_fstat_local(replay_r)
                        replay_w_stat = _safe_fstat_local(replay_w)
                        for pfd, expected_stat in ((replay_r, replay_r_stat), (replay_w, replay_w_stat)):
                            if expected_stat is None or expected_stat[2] != stat.S_IFIFO or _safe_fstat_local(pfd) != expected_stat:
                                raise RuntimeError("Replay pipe identity held")
                            fl = fcntl.fcntl(pfd, fcntl.F_GETFL)
                            if _safe_fstat_local(pfd) != expected_stat:
                                raise RuntimeError("Replay pipe identity held")
                            fcntl.fcntl(pfd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
                            if _safe_fstat_local(pfd) != expected_stat:
                                raise RuntimeError("Replay pipe identity held")
                            descriptor_flags = fcntl.fcntl(pfd, fcntl.F_GETFD)
                            if _safe_fstat_local(pfd) != expected_stat:
                                raise RuntimeError("Replay pipe identity held")
                            fcntl.fcntl(pfd, fcntl.F_SETFD, descriptor_flags | fcntl.FD_CLOEXEC)
                            if _safe_fstat_local(pfd) != expected_stat:
                                raise RuntimeError("Replay pipe identity held")

                    if replay_r < 0 or replay_w < 0 or replay_r_stat is None or replay_w_stat is None:
                        raise RuntimeError("Replay pipe allocation failed")

                    if _safe_fstat_local(replay_w) != replay_w_stat:
                        raise RuntimeError("Replay pipe writer altered before close")
                    target_w = replay_w
                    replay_w = -1
                    if not _close_fd_no_retry_local(target_w):
                        cleanup_uncertain = True
                        raise RuntimeError("Replay pipe writer close failed")

                    ctx_copy2 = copy.deepcopy(validated_ctx)
                    rec_copy2 = copy.deepcopy(validated_rec)
                    rcpt_copy2 = copy.deepcopy(validated_rcpt)
                    replay_result = self.server.import_cb(
                        ctx_copy2,
                        rec_copy2,
                        rcpt_copy2,
                        replay_r,
                        cancel_event,
                        http_deadline,
                    )

                    validated_replay_result = validate_import_result(
                        replay_result,
                        validated_ctx,
                        validated_rec,
                        validated_rcpt,
                    )

                    if not (validated_replay_result["replay_stage"] is True and validated_replay_result["replay_journal"] is True):
                        raise RuntimeError("Replay revalidation flags not both True")
                except (KeyboardInterrupt, SystemExit) as r_exc:
                    orig_cb_exc = r_exc
                    raise
                except Exception:
                    self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                    return
                finally:
                    if replay_w >= 0:
                        target_w = replay_w
                        replay_w = -1
                        if _safe_fstat_local(target_w) == replay_w_stat:
                            if not _close_fd_no_retry_local(target_w):
                                cleanup_uncertain = True
                        else:
                            cleanup_uncertain = True
                    if replay_r >= 0:
                        target_r = replay_r
                        replay_r = -1
                        if _safe_fstat_local(target_r) == replay_r_stat:
                            if _close_fd_no_retry_local(target_r):
                                replay_r_closed = True
                            else:
                                cleanup_uncertain = True
                        else:
                            cleanup_uncertain = True

                if not replay_r_closed or cleanup_uncertain:
                    self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                    return

            now = time.monotonic()
            if cancel_event.is_set() or now >= http_deadline:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            ack_payload = {
                "schema": "sg.local-cipher-import.v1",
                "state": "cipher-journal-bound",
                "context": copy.deepcopy(validated_ctx),
                "job_id": validated_rec["job_id"],
                "request_digest": validated_rec["request_digest"],
                "artifact": copy.deepcopy(validated_rec["artifact"]),
                "replay_stage": bool(initial_replay_stage),
                "replay_journal": bool(initial_replay_journal),
            }
            try:
                serialized = json.dumps(ack_payload, allow_nan=False).encode("utf-8")
                if len(serialized) > 4096:
                    raise ValueError("Response exceeds 4096 bytes")
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if bridge is not None and not bridge.worker_quiescent:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if cleanup_uncertain:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            try:
                unregister_attempted = True
                self.server.import_request_registry.unregister(reg_handle)
                registry_registered = False
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                cleanup_uncertain = True
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            try:
                gate_end_attempted = True
                self.server.gate.end_mutation()
                gate_held = False
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                cleanup_uncertain = True
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            success_response_bytes = serialized

        finally:
            inflight = sys.exc_info()[1]
            primary_controlflow = orig_cb_exc if isinstance(orig_cb_exc, (KeyboardInterrupt, SystemExit)) else (inflight if isinstance(inflight, (KeyboardInterrupt, SystemExit)) else None)
            if bridge is not None and not finish_succeeded:
                try:
                    bridge.abort()
                except (KeyboardInterrupt, SystemExit) as c_exc:
                    cleanup_uncertain = True
                    if orig_cb_exc is None:
                        orig_cb_exc = c_exc
                except Exception:
                    cleanup_uncertain = True
            if bridge is not None and (gate_held or registry_registered):
                try:
                    if bridge.worker_quiescent is not True:
                        cleanup_uncertain = True
                except (KeyboardInterrupt, SystemExit) as c_exc:
                    cleanup_uncertain = True
                    if orig_cb_exc is None:
                        orig_cb_exc = c_exc
                except Exception:
                    cleanup_uncertain = True

            if registry_registered and reg_handle is not None and not unregister_attempted:
                if not cleanup_uncertain:
                    try:
                        unregister_attempted = True
                        self.server.import_request_registry.unregister(reg_handle)
                        registry_registered = False
                    except (KeyboardInterrupt, SystemExit) as c_exc:
                        if orig_cb_exc is None:
                            orig_cb_exc = c_exc
                        cleanup_uncertain = True
                    except Exception:
                        cleanup_uncertain = True

            if gate_held and not gate_end_attempted:
                if not cleanup_uncertain:
                    try:
                        gate_end_attempted = True
                        self.server.gate.end_mutation()
                        gate_held = False
                    except (KeyboardInterrupt, SystemExit) as c_exc:
                        if orig_cb_exc is None:
                            orig_cb_exc = c_exc
                    except Exception:
                        pass

            if primary_controlflow is not None:
                raise primary_controlflow
            if isinstance(orig_cb_exc, (KeyboardInterrupt, SystemExit)):
                raise orig_cb_exc

        if success_response_bytes is not None and cancel_event is not None:
            self._send_bounded_import_response(success_response_bytes, cancel_event, http_deadline)

    def _handle_export(self, raw_body: bytes) -> None:
        http_deadline = time.monotonic() + 15.0
        payload = self._parse_and_validate_payload(False, raw_body)
        if payload is None:
            return

        if time.monotonic() >= http_deadline:
            self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            return

        if self.server.export_cb is None:
            self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            return

        try:
            from .runtime_cipher_export import CheckpointExportReader
        except ImportError:
            self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            return

        reader = None
        gate_acquired = False
        headers_started = False
        try:
            try:
                reader = self.server.export_cb(dict(payload))
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if time.monotonic() >= http_deadline:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if type(reader) is not CheckpointExportReader:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            try:
                self.server.gate.begin_mutation()
                gate_acquired = True
            except RuntimeError:
                self._send_response_raw(409, "text/plain; charset=utf-8", b"Conflict")
                return

            if time.monotonic() >= http_deadline:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            try:
                reader.__enter__()
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if time.monotonic() >= http_deadline:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            try:
                m_ctx, m_rec = reader.manifest()
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if time.monotonic() >= http_deadline:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if type(m_ctx) is not dict or m_ctx != self.server.operation_context:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            try:
                canonical_bytes = _serialize_record(m_rec)
                parsed_rec = _parse_and_validate_record(canonical_bytes)
                if parsed_rec != m_rec:
                    raise ValueError("Record mismatch")
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if (
                parsed_rec.get("schema") != "sg.local-job.v1"
                or parsed_rec.get("job_id") != payload["job_id"]
                or parsed_rec.get("request_digest") != payload["request_digest"]
                or parsed_rec.get("state") != "artifact-verified"
            ):
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            art = parsed_rec.get("artifact")
            if not isinstance(art, dict) or set(art.keys()) != {"leaf", "bytes", "sha256"}:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            expected_leaf = f"sg-encrypted-{payload['job_id']}.bin"
            if art["leaf"] != expected_leaf:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            total_bytes = art["bytes"]
            if type(total_bytes) is not int or isinstance(total_bytes, bool) or not (1 <= total_bytes <= MAX_CIPHER_BYTES):
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            export_digest = art["sha256"]
            if type(export_digest) is not str or not HEX64_RE.fullmatch(export_digest):
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            try:
                ctx_header_val = json.dumps(self.server.operation_context, separators=(",", ":"), sort_keys=True)
                rec_header_val = json.dumps(parsed_rec, separators=(",", ":"))
                if len(ctx_header_val.encode("ascii")) > 2048 or len(rec_header_val.encode("ascii")) > 2048:
                    raise ValueError("Header too large")
            except Exception:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if time.monotonic() >= http_deadline:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            headers_started = True
            sock = self.connection
            try:
                rem_time = http_deadline - time.monotonic()
                if rem_time <= 0:
                    raise TimeoutError("Export deadline")
                sock.settimeout(rem_time)
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.sg.cipher-export+v1")
                self.send_header("Content-Length", str(total_bytes))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.send_header("X-SG-Export-Context", ctx_header_val)
                self.send_header("X-SG-Export-Record", rec_header_val)
                self.send_header("X-SG-Export-Digest", export_digest)
                remaining = http_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Export deadline")
                sock.settimeout(remaining)
                self.end_headers()
                if time.monotonic() >= http_deadline:
                    raise TimeoutError("Export deadline")
            except Exception:
                self.close_connection = True
                return

            try:
                it = reader.iter_chunks()
            except Exception:
                self.close_connection = True
                return

            sent_bytes = 0
            try:
                for chunk in it:
                    if type(chunk) is not bytes or len(chunk) == 0 or len(chunk) > 65536:
                        raise RuntimeError("Invalid chunk")
                    chunk_view = memoryview(chunk)
                    while len(chunk_view) > 0:
                        rem_time = http_deadline - time.monotonic()
                        if rem_time <= 0:
                            raise TimeoutError("Export deadline")
                        sock.settimeout(rem_time)
                        to_send = chunk_view[: min(len(chunk_view), 4096)]
                        nw = sock.send(to_send)
                        if nw <= 0:
                            raise RuntimeError("Socket write error")
                        sent_bytes += nw
                        chunk_view = chunk_view[nw:]
                        if time.monotonic() >= http_deadline:
                            raise TimeoutError("Export deadline")
                if sent_bytes != total_bytes:
                    raise RuntimeError("Incomplete stream")
            except Exception:
                self.close_connection = True
                return
            finally:
                if hasattr(it, "close"):
                    try:
                        it.close()
                    except Exception:
                        pass
        except Exception:
            if not headers_started:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            self.close_connection = True
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
            if gate_acquired:
                try:
                    self.server.gate.end_mutation()
                except Exception:
                    self.close_connection = True
            self.close_connection = True

    def do_POST(self) -> None:
        if not self._validate_auth():
            self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
            return
        raw_path = self.raw_requestline.split()[1].decode("ascii", errors="ignore") if hasattr(self, "raw_requestline") else self.path
        if "?" in raw_path or "%" in raw_path or "//" in raw_path:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return
        if self.path == "/_management/import":
            self._handle_import()
            return
        if self.path == "/_management/export":
            body = self._read_body()
            if body is None:
                return
            self._handle_export(body)
            return
        if self.path not in ("/_management/checkpoint", "/_management/restore"):
            self._send_response_raw(404, "text/plain; charset=utf-8", b"Not Found")
            return

        body = self._read_body()
        if body is None:
            return
        is_restore = (self.path == "/_management/restore")
        payload = self._parse_and_validate_payload(is_restore, body)
        if payload is None:
            return

        try:
            self.server.gate.begin_mutation()
        except RuntimeError:
            self._send_response_raw(409, "text/plain; charset=utf-8", b"Conflict")
            return

        try:
            cb = self.server.restore_cb if is_restore else self.server.checkpoint_cb
            res = cb(payload)
            if type(res) is not dict:
                raise RuntimeError("Callback result held")
            res_bytes = json.dumps(res, allow_nan=False).encode("utf-8")
            if len(res_bytes) > 4096:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return
            self._send_response_raw(200, "application/json", res_bytes)
        except Exception:
            self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
        finally:
            self.server.gate.end_mutation()

    def _handle_unsupported(self) -> None:
        if not self._validate_auth():
            self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
            return
        self._send_response_raw(405, "text/plain; charset=utf-8", b"Method Not Allowed")

    do_GET = _handle_unsupported
    do_PUT = _handle_unsupported
    do_DELETE = _handle_unsupported
    do_HEAD = _handle_unsupported
    do_OPTIONS = _handle_unsupported
    do_PATCH = _handle_unsupported


def create_management_server(
    checkpoint: Callable[[dict[str, Any]], dict[str, Any]],
    restore: Callable[[dict[str, Any]], dict[str, Any]],
    management_key: str,
    backend_key: str,
    storage_key: str,
    *,
    operation_context: dict[str, Any],
    export_cb: Callable[[dict[str, Any]], CheckpointExportReader] | None = None,
    import_cb: Callable[..., dict[str, Any]] | None = None,
    import_request_registry: ImportRequestRegistry | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    max_connections: int = 8,
    connection_timeout: float = 1.0,
    gate: OperationGate | None = None,
) -> ThreadingHTTPServer:
    checkpoint_digest(operation_context, "0" * 32)
    trusted_context = copy.deepcopy(operation_context)
    if not callable(checkpoint) or not callable(restore):
        raise ValueError("Callbacks must be callable")
    if export_cb is not None and not callable(export_cb):
        raise ValueError("Export callback must be callable")
    if import_cb is not None and not callable(import_cb):
        raise ValueError("Import callback must be callable")
    if import_request_registry is not None and type(import_request_registry) is not ImportRequestRegistry:
        raise ValueError("import_request_registry must be an ImportRequestRegistry instance")
    for name, k in [("management_key", management_key), ("backend_key", backend_key), ("storage_key", storage_key)]:
        if not isinstance(k, str) or not KEY_RE.fullmatch(k):
            raise ValueError(f"Invalid key for {name}")
    if len({management_key, backend_key, storage_key}) != 3:
        raise ValueError("Keys must be distinct")
    if host not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("Host must be 127.0.0.1 or 0.0.0.0")
    if not isinstance(port, int) or isinstance(port, bool) or port < 0 or port > 65535:
        raise ValueError("Port must be int in 0..65535")
    if not isinstance(max_connections, int) or isinstance(max_connections, bool) or max_connections < 1 or max_connections > 32:
        raise ValueError("max_connections must be int in 1..32")
    if isinstance(connection_timeout, bool) or not isinstance(connection_timeout, (int, float)) or not (0.05 <= connection_timeout <= 5.0):
        raise ValueError("connection_timeout must be float in 0.05..5.0")
    server_gate = gate if gate is not None else OperationGate()
    registry = import_request_registry if import_request_registry is not None else (ImportRequestRegistry() if import_cb is not None else None)
    return _ManagementServer(
        (host, port),
        _ManagementHandler,
        checkpoint,
        restore,
        export_cb,
        import_cb,
        registry,
        management_key,
        max_connections,
        float(connection_timeout),
        server_gate,
        trusted_context,
    )

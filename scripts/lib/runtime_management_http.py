"""Authenticated local management HTTP listener with OperationGate concurrency control."""
from __future__ import annotations

import copy
import hmac
import json
import re
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime_cipher_export import CheckpointExportReader

try:
    from .runtime_job_journal import _parse_and_validate_record, _serialize_record
    from .runtime_operation_identity import checkpoint_digest, validate_checkpoint, validate_restore
except ImportError:
    from lib.runtime_job_journal import _parse_and_validate_record, _serialize_record
    from lib.runtime_operation_identity import checkpoint_digest, validate_checkpoint, validate_restore

KEY_RE = re.compile(r"^[A-Za-z0-9._~-]{32,256}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
LEAF_RE = re.compile(r"^sg-encrypted-[0-9a-f]{32}\.bin$")
MAX_RESTORE_BYTES = 64 * 1024 * 1024 + 4136
MAX_CIPHER_BYTES = 64 * 1024 * 1024 + 4136


class OperationGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_tokens: set[object] = set()
        self._mutating = False

    def begin_stream(self) -> object:
        with self._lock:
            if self._mutating:
                raise RuntimeError("Mutation in progress")
            token = object()
            self._active_tokens.add(token)
            return token

    def end_stream(self, token: object) -> None:
        with self._lock:
            if token not in self._active_tokens:
                raise RuntimeError("Invalid stream token")
            self._active_tokens.remove(token)

    def begin_mutation(self) -> None:
        with self._lock:
            if self._mutating or len(self._active_tokens) > 0:
                raise RuntimeError("Cannot begin mutation: active operations present")
            self._mutating = True

    def end_mutation(self) -> None:
        with self._lock:
            if not self._mutating:
                raise RuntimeError("No mutation in progress")
            self._mutating = False


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
    return _ManagementServer(
        (host, port),
        _ManagementHandler,
        checkpoint,
        restore,
        export_cb,
        management_key,
        max_connections,
        float(connection_timeout),
        server_gate,
        trusted_context,
    )

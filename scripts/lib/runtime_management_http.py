"""Authenticated local management HTTP listener with OperationGate concurrency control."""
from __future__ import annotations
from lib.runtime_operation_identity import checkpoint_digest, validate_checkpoint, validate_restore

import hmac
import json
import re
import select
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

KEY_RE = re.compile(r"^[A-Za-z0-9._~-]{32,256}$")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
LEAF_RE = re.compile(r"^sg-encrypted-[0-9a-f]{32}\.bin$")
MAX_RESTORE_BYTES = 64 * 1024 * 1024 + 4136


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
    def __init__(self, raw, connection, deadline, limit=32768):
        self.raw = raw
        self.connection = connection
        self.deadline = deadline
        self.remaining = limit

    def readline(self, size=-1):
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

    def __init__(self, server_address: tuple[str, int], RequestHandlerClass: type,
                 checkpoint_cb: Callable[[dict], dict], restore_cb: Callable[[dict], dict],
                 management_key: str, max_conn: int, conn_timeout: float, gate: OperationGate, operation_context: dict) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.operation_context = operation_context
        self.checkpoint_cb = checkpoint_cb
        self.restore_cb = restore_cb
        self.management_key = management_key
        self.conn_timeout = conn_timeout
        self.gate = gate
        self.conn_semaphore = threading.Semaphore(max_conn)

    def handle_error(self, request, client_address):
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

    def __getattr__(self, name):
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

    def parse_request(self):
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

        # Check for pipelined/extra bytes
        r, _, _ = select.select([sock], [], [], 0.0)
        if r:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        return bytes(body)

    def _parse_and_validate_payload(self, is_restore: bool, raw_body: bytes) -> dict | None:
        try:
            text = raw_body.decode("utf-8")
            seen_keys: set[str] = set()
            def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict:
                res = {}
                for k, v in pairs:
                    if k in seen_keys:
                        raise ValueError("Duplicate key")
                    seen_keys.add(k)
                    res[k] = v
                return res
            data = json.loads(text, object_pairs_hook=_pairs_hook, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid constant")))
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

    def do_POST(self) -> None:
        if not self._validate_auth():
            self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
            return
        raw_path = self.raw_requestline.split()[1].decode("ascii", errors="ignore") if hasattr(self, "raw_requestline") else self.path
        if "?" in raw_path or "%" in raw_path or "//" in raw_path:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
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


def create_management_server(checkpoint: Callable[[dict], dict], restore: Callable[[dict], dict],
                             management_key: str, backend_key: str, storage_key: str, *,
                             operation_context: dict, host: str = "127.0.0.1", port: int = 0,
                             max_connections: int = 8, connection_timeout: float = 1.0,
                             gate: OperationGate | None = None) -> ThreadingHTTPServer:
    checkpoint_digest(operation_context, "0" * 32)
    trusted_context = dict(operation_context)
    if not callable(checkpoint) or not callable(restore):
        raise ValueError("Callbacks must be callable")
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
    return _ManagementServer((host, port), _ManagementHandler, checkpoint, restore,
                           management_key, max_connections, float(connection_timeout), server_gate, trusted_context)

"""Generic authenticated read-only readiness HTTP boundary server candidate."""

import hmac
import json
import math
import re
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Callable, Any

__all__ = ["create_readiness_server"]

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{32,256}$")
_ALLOWED_HOSTS = {"127.0.0.1", "0.0.0.0"}
_KNOWN_METHODS = {
    "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"
}


class _ReadinessRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    _MAX_RAW_HEADER_BYTES = 32768

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress all default logging and unsanitized output
        pass

    def log_error(self, format: str, *args: Any) -> None:
        # Suppress unsanitized error logging
        pass

    def send_error(self, code, message=None, explain=None):
        # Parser errors must never echo the supplied method, target or version.
        if getattr(self, "request_version", "HTTP/0.9") == "HTTP/0.9":
            self.request_version = "HTTP/1.1"
        self._send_response_payload(code, b"bad request\n", "text/plain; charset=utf-8",
                                    is_head=getattr(self, "command", "") == "HEAD")

    def handle_expect_100(self) -> bool:
        # Never send 100-continue; perform auth check or reject
        if not self._check_auth():
            self._send_response_payload(401, b"unauthorized\n", "text/plain; charset=utf-8", is_head=False)
            return False
        self._send_response_payload(400, b"bad request\n", "text/plain; charset=utf-8", is_head=False)
        return False

    def parse_request(self) -> bool:
        # Read and check raw header line size limits
        raw_bytes_read = len(self.raw_requestline)
        peek_buf = []
        while True:
            line = self.rfile.readline(self._MAX_RAW_HEADER_BYTES + 1)
            if not line:
                break
            raw_bytes_read += len(line)
            if raw_bytes_read > self._MAX_RAW_HEADER_BYTES:
                self._send_response_payload(431, b"request header fields too large\n", "text/plain; charset=utf-8", is_head=False)
                return False
            peek_buf.append(line)
            if line in (b"\r\n", b"\n", b""):
                break

        # Feed lines back into rfile
        all_bytes = b"".join(peek_buf)
        
        # Custom parse using base logic on memory buffer
        import io
        self.rfile = io.BytesIO(all_bytes)
        return super().parse_request()

    def _check_auth(self) -> bool:
        server = self.server
        # Headers are parsed in self.headers
        auth_headers = self.headers.get_all("authorization", [])
        if len(auth_headers) != 1:
            return False

        raw_auth = auth_headers[0]
        if not raw_auth.startswith("Bearer "):
            return False

        token = raw_auth[7:]
        # Token must match allowed chars directly and exact length
        if not _KEY_PATTERN.fullmatch(token):
            return False

        valid = False
        for allowed_key in server._valid_keys:
            if hmac.compare_digest(token, allowed_key):
                valid = True

        return valid

    def _send_response_payload(self, status_code: int, body: bytes, content_type: str, is_head: bool = False) -> None:
        try:
            self.send_response_only(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not is_head and body:
                self.wfile.write(body)
                self.wfile.flush()
        except Exception:
            pass
        finally:
            self.close_connection = True

    def handle_one_request(self) -> None:
        try:
            self.request_version = "HTTP/1.1"
            self.command = ""
            self.raw_requestline = self.rfile.readline(self._MAX_RAW_HEADER_BYTES + 1)
            if len(self.raw_requestline) > self._MAX_RAW_HEADER_BYTES:
                self._send_response_payload(431, b"request header fields too large\n", "text/plain; charset=utf-8", is_head=False)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            self._dispatch_request()
        except Exception:
            self._send_response_payload(500, b"internal server error\n", "text/plain; charset=utf-8", is_head=False)
        finally:
            self.close_connection = True

    def _dispatch_request(self) -> None:
        method = getattr(self, "command", "").strip()
        is_head = (method == "HEAD")

        # 1. Auth check first regardless of method, url, or headers
        if not self._check_auth():
            self._send_response_payload(401, b"unauthorized\n", "text/plain; charset=utf-8", is_head=is_head)
            return

        # 2. Reject unsupported headers / bodies before probe
        # Reject Transfer-Encoding or Expect
        if "transfer-encoding" in self.headers or "expect" in self.headers:
            self._send_response_payload(400, b"bad request\n", "text/plain; charset=utf-8", is_head=is_head)
            return

        # Duplicate Content-Length or non-zero / malformed content length
        cl_headers = self.headers.get_all("content-length", [])
        if len(cl_headers) > 1:
            self._send_response_payload(400, b"bad request\n", "text/plain; charset=utf-8", is_head=is_head)
            return
        if len(cl_headers) == 1:
            cl_val = cl_headers[0]
            if not cl_val.isdigit() or cl_val != "0":
                self._send_response_payload(400, b"bad request\n", "text/plain; charset=utf-8", is_head=is_head)
                return

        # 3. Check method
        if method != "GET":
            self._send_response_payload(405, b"method not allowed\n", "text/plain; charset=utf-8", is_head=is_head)
            return

        # 4. Target validation (raw path without normalization/escaping/query)
        parts = self.raw_requestline.rstrip(b"\r\n").split(b" ")
        raw_path = parts[1].decode("iso-8859-1") if len(parts) == 3 else ""

        if raw_path not in ("/healthz", "/_management/ready"):
            # If path has query, absolute URL, double slashes, percent encoding, or control chars
            if any(c in raw_path for c in ("?", "#", "%", "//")) or not raw_path.startswith("/"):
                self._send_response_payload(400, b"bad request\n", "text/plain; charset=utf-8", is_head=is_head)
                return
            self._send_response_payload(404, b"not found\n", "text/plain; charset=utf-8", is_head=is_head)
            return

        # 5. Call probe
        probe_ok = False
        try:
            res = self.server._probe()
            if res is True:
                probe_ok = True
        except Exception:
            probe_ok = False

        if not probe_ok:
            if raw_path == "/healthz":
                self._send_response_payload(503, b"not_ready\n", "text/plain; charset=utf-8", is_head=is_head)
            else:
                self._send_response_payload(503, b'{"status":"not_ready"}\n', "application/json", is_head=is_head)
            return

        # 6. Success response
        if raw_path == "/healthz":
            self._send_response_payload(200, b"ok\n", "text/plain; charset=utf-8", is_head=is_head)
        else:
            ready_body = json.dumps({"status": "ready", "lifecycle": "running"}, separators=(",", ":")).encode("utf-8") + b"\n"
            self._send_response_payload(200, ready_body, "application/json", is_head=is_head)


class _BoundedThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, server_address: tuple[str, int], RequestHandlerClass: type, probe: Callable[[], bool], valid_keys: tuple[str, ...], max_connections: int, connection_timeout: float):
        self._probe = probe
        self._valid_keys = valid_keys
        self._semaphore = threading.BoundedSemaphore(max_connections)
        self._connection_timeout = connection_timeout
        super().__init__(server_address, RequestHandlerClass, bind_and_activate=True)

    def get_request(self) -> tuple[Any, Any]:
        sock, addr = super().get_request()
        sock.settimeout(self._connection_timeout)
        return sock, addr

    def process_request(self, request: Any, client_address: Any) -> None:
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            finally:
                try:
                    request.close()
                except Exception:
                    pass
            return

        def worker():
            try:
                self.finish_request(request, client_address)
            except Exception:
                self.handle_error(request, client_address)
            finally:
                try:
                    self.shutdown_request(request)
                except Exception:
                    pass
                self._semaphore.release()

        try:
            t = threading.Thread(target=worker, daemon=self.daemon_threads)
            t.start()
        except Exception:
            try:
                self.shutdown_request(request)
            except Exception:
                pass
            self._semaphore.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Suppress unsanitized tracebacks to stderr/stdout
        pass


def create_readiness_server(
    probe: Callable[[], bool],
    management_key: str,
    backend_key: str,
    storage_key: str,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    max_connections: int = 8,
    connection_timeout: float = 1.0,
) -> _BoundedThreadingHTTPServer:
    """Creates a bounded, authenticated read-only readiness ThreadingHTTPServer instance (not started)."""
    # 1. Validate probe
    if not callable(probe):
        raise ValueError("Invalid readiness server configuration")

    # 2. Validate distinct keys matching [A-Za-z0-9._~-]{32,256}
    keys = [management_key, backend_key, storage_key]
    for k in keys:
        if not isinstance(k, str) or not _KEY_PATTERN.fullmatch(k):
            raise ValueError("Invalid readiness server configuration")
    if len(set(keys)) != 3:
        raise ValueError("Invalid readiness server configuration")

    # 3. Validate host
    if not isinstance(host, str) or host not in _ALLOWED_HOSTS:
        raise ValueError("Invalid readiness server configuration")

    # 4. Validate port (exact int 0..65535, reject bool)
    if isinstance(port, bool) or not isinstance(port, int) or port < 0 or port > 65535:
        raise ValueError("Invalid readiness server configuration")

    # 5. Validate max_connections (exact int 1..32, reject bool)
    if isinstance(max_connections, bool) or not isinstance(max_connections, int) or max_connections < 1 or max_connections > 32:
        raise ValueError("Invalid readiness server configuration")

    # 6. Validate connection_timeout (finite float/int 0 < value <= 5, reject bool)
    if isinstance(connection_timeout, bool) or not isinstance(connection_timeout, (int, float)):
        raise ValueError("Invalid readiness server configuration")
    if math.isnan(connection_timeout) or math.isinf(connection_timeout) or connection_timeout <= 0 or connection_timeout > 5:
        raise ValueError("Invalid readiness server configuration")

    try:
        server = _BoundedThreadingHTTPServer(
            server_address=(host, port),
            RequestHandlerClass=_ReadinessRequestHandler,
            probe=probe,
            valid_keys=(management_key,),
            max_connections=max_connections,
            connection_timeout=float(connection_timeout),
        )
    except Exception as exc:
        raise ValueError("Invalid readiness server configuration") from exc

    return server

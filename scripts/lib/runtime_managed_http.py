"""Authenticated local managed HTTP listener with backend streaming and gate control."""
from __future__ import annotations

import http.client
import math
import hmac
import json
import queue
import re
import select
import socket
import threading
import time
from typing import Any, Callable

from lib.runtime_management_http import KEY_RE, OperationGate, _ManagementHandler, _BoundedHeaderReader, create_management_server


class _BoundedUpstreamResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, deadline, **kwargs):
        self._owned_socket = sock
        self._deadline = deadline
        super().__init__(sock, *args, **kwargs)

    def begin(self):
        original = self.fp
        reader = _BoundedHeaderReader(original, self._owned_socket, self._deadline, limit=32768)
        reader.close = original.close
        self.fp = reader
        try:
            super().begin()
        finally:
            if self.fp is reader:
                self.fp = original

class _ManagedProxyHandler(_ManagementHandler):
    def _check_raw_path(self, expected: str) -> bool:
        raw = self.raw_requestline.split()[1].decode("ascii", errors="ignore") if hasattr(self, "raw_requestline") else self.path
        if "?" in raw or "%" in raw or "//" in raw or raw != expected or self.path != expected:
            return False
        return True

    def _validate_backend_auth(self) -> bool:
        auths = self.headers.get_all("Authorization", [])
        if len(auths) != 1:
            return False
        parts = auths[0].split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer" or not KEY_RE.fullmatch(parts[1]):
            return False
        return hmac.compare_digest(parts[1].encode("ascii"), self.server.backend_key.encode("ascii"))

    def do_GET(self) -> None:
        raw = self.raw_requestline.split()[1].decode("ascii", errors="ignore") if hasattr(self, "raw_requestline") else self.path
        if "?" in raw or "%" in raw or "//" in raw:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return
        if self.path == "/healthz":
            try:
                res = self.server.health_probe()
            except Exception:
                res = False
            if res is True:
                self._send_response_raw(200, "text/plain; charset=utf-8", b"ok\n")
            else:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            return
        if self.path == "/_management/ready":
            if not self._validate_auth():
                self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
                return
            try:
                ready = self.server.health_probe() is True
            except Exception:
                ready = False
            body = b'{"ready":true}' if ready else b'{"ready":false}'
            self._send_response_raw(200 if ready else 503, "application/json", body)
            return
        if self.path == "/v1/models":
            if not self._validate_backend_auth():
                self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if "Transfer-Encoding" in self.headers or "Expect" in self.headers or (lengths and lengths != ["0"]):
                self._send_response_raw(400, "text/plain", b"Bad Request")
                return
            self._forward_backend("GET", "/v1/models", None)
            return
        if self.path in ("/_management/checkpoint", "/_management/restore", "/v1/chat/completions"):
            if not self._validate_auth() and not self._validate_backend_auth():
                self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
                return
            self._send_response_raw(405, "text/plain; charset=utf-8", b"Method Not Allowed")
            return
        self._send_response_raw(404, "text/plain; charset=utf-8", b"Not Found")

    def do_POST(self) -> None:
        raw = self.raw_requestline.split()[1].decode("ascii", errors="ignore") if hasattr(self, "raw_requestline") else self.path
        if "?" in raw or "%" in raw or "//" in raw:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return
        if self.path in ("/_management/checkpoint", "/_management/restore"):
            super().do_POST()
            return
        if self.path == "/v1/chat/completions":
            if not self._validate_backend_auth():
                self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
                return
            try:
                admitted = self.server.admission_probe() is True
            except Exception:
                admitted = False
            if not admitted:
                self._send_response_raw(503, "text/plain", b"Service Unavailable")
                return
            body = self._read_backend_body()
            if body is None:
                return
            self._forward_backend("POST", "/v1/chat/completions", body)
            return
        if self.path in ("/healthz", "/_management/ready", "/v1/models"):
            if not self._validate_auth() and not self._validate_backend_auth():
                self._send_response_raw(401, "text/plain; charset=utf-8", b"Unauthorized")
                return
            self._send_response_raw(405, "text/plain; charset=utf-8", b"Method Not Allowed")
            return
        self._send_response_raw(404, "text/plain; charset=utf-8", b"Not Found")

    def _read_backend_body(self) -> bytes | None:
        if "Transfer-Encoding" in self.headers or "Expect" in self.headers:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        cls = self.headers.get_all("Content-Length", [])
        if len(cls) != 1 or not cls[0].isdigit() or cls[0].startswith(("+", "-")):
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        length = int(cls[0])
        if length < 1 or length > 1048576 or str(length) != cls[0]:
            status = 413 if length > 1048576 else 400
            self._send_response_raw(status, "text/plain; charset=utf-8", b"Payload Too Large" if status == 413 else b"Bad Request")
            return None
        cts = self.headers.get_all("Content-Type", [])
        if len(cts) != 1 or cts[0].strip() != "application/json":
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        body = bytearray()
        sock = self.connection
        deadline = time.monotonic() + 5.0
        while len(body) < length:
            rem = deadline - time.monotonic()
            if rem <= 0:
                self._send_response_raw(408, "text/plain; charset=utf-8", b"Request Timeout")
                return None
            r, _, _ = select.select([sock], [], [], min(rem, 0.5))
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
        try:
            def _pairs(pairs: list[tuple[str, Any]]) -> dict:
                seen: set[str] = set()
                res = {}
                for k, v in pairs:
                    if k in seen:
                        raise ValueError("Duplicate key")
                    seen.add(k)
                    res[k] = v
                return res
            data = json.loads(body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=lambda v: (_ for _ in ()).throw(ValueError()))
            if not isinstance(data, dict):
                raise ValueError()
        except Exception:
            self._send_response_raw(400, "text/plain; charset=utf-8", b"Bad Request")
            return None
        return bytes(body)

    def _forward_backend(self, method: str, path: str, body: bytes | None) -> None:
        try:
            token = self.server.gate.begin_stream()
        except RuntimeError:
            self._send_response_raw(409, "text/plain; charset=utf-8", b"Conflict")
            return

        conn = None
        resp = None
        reader_thread = None
        stream_headers_started = False
        try:
            if method == "POST" and self.server.admission_probe() is not True:
                raise RuntimeError("Admission held")
            upstream_deadline = time.monotonic() + self.server.upstream_timeout
            conn = http.client.HTTPConnection("127.0.0.1", self.server.upstream_port, timeout=self.server.upstream_timeout)
            conn.response_class = lambda *args, **kwargs: _BoundedUpstreamResponse(*args, deadline=upstream_deadline, **kwargs)
            headers = {}
            if body is not None:
                headers["Content-Type"] = "application/json"
                headers["Content-Length"] = str(len(body))
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            if not (200 <= status <= 599):
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return
            if not (200 <= status <= 299):
                self._send_response_raw(status, "text/plain; charset=utf-8", b"Error")
                return
            ct = resp.getheader("Content-Type", "").strip()
            media_type = ct.split(";", 1)[0].strip().lower()
            is_sse = media_type == "text/event-stream"
            is_json = media_type == "application/json"
            if not is_sse and not is_json:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                return

            if not is_sse:
                resp_body = bytearray()
                while True:
                    remaining = upstream_deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Upstream held")
                    if resp.fp is not None:
                        resp.fp.raw._sock.settimeout(remaining)
                    chunk = resp.read1(16384)
                    if time.monotonic() >= upstream_deadline:
                        raise TimeoutError("Upstream held")
                    if not chunk:
                        if resp.length not in (None, 0):
                            raise RuntimeError("Upstream held")
                        break
                    resp_body.extend(chunk)
                    if len(resp_body) > 1048576:
                        self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
                        return
                self._send_response_raw(status, "application/json", bytes(resp_body))
                return

            # SSE Streaming path
            try:
                stream_headers_started = True
                self.send_response(status)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
            except Exception:
                return

            q: queue.Queue[bytes | None | Exception] = queue.Queue(maxsize=2)
            stop_ev = threading.Event()

            upstream_socket = resp.fp.raw._sock
            upstream_socket.settimeout(30.0)

            def _offer(item):
                while not stop_ev.is_set():
                    try:
                        q.put(item, timeout=0.1)
                        return
                    except queue.Full:
                        continue

            def _reader_thread() -> None:
                try:
                    while not stop_ev.is_set():
                        try:
                            chunk = resp.read1(16384)
                        except socket.timeout:
                            _offer(RuntimeError("Stream held"))
                            break
                        except Exception as e:
                            if not stop_ev.is_set():
                                _offer(e)
                            break
                        if not chunk:
                            _offer(None)
                            break
                        while not stop_ev.is_set():
                            try:
                                q.put(chunk, timeout=0.1)
                                break
                            except queue.Full:
                                continue
                except Exception as e:
                    if not stop_ev.is_set():
                        try:
                            q.put(e, timeout=0.1)
                        except Exception:
                            pass

            t = threading.Thread(target=_reader_thread, daemon=True)
            reader_thread = t
            t.start()
            total_dl = time.monotonic() + 120.0
            idle_dl = time.monotonic() + 30.0
            client_sock = self.connection
            orig_timeout = client_sock.gettimeout()
            client_sock.settimeout(1.0)
            stream_ok = True
            try:
                while stream_ok:
                    now = time.monotonic()
                    if now >= total_dl or now >= idle_dl:
                        break
                    r, _, x = select.select([client_sock], [], [client_sock], 0.05)
                    if x:
                        break
                    if r:
                        try:
                            peek = client_sock.recv(1, socket.MSG_PEEK)
                            if not peek:
                                break
                        except Exception:
                            break
                    try:
                        item = q.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if item is None or isinstance(item, Exception):
                        break
                    idle_dl = time.monotonic() + 30.0
                    try:
                        self.wfile.write(item)
                        self.wfile.flush()
                    except Exception:
                        stream_ok = False
                        break
            finally:
                stop_ev.set()
                try:
                    upstream_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                t.join(timeout=2.0)
                try:
                    client_sock.settimeout(orig_timeout)
                except Exception:
                    pass
                self.close_connection = True
        except Exception:
            if not stream_headers_started:
                self._send_response_raw(503, "text/plain; charset=utf-8", b"Service Unavailable")
            else:
                self.close_connection = True
        finally:
            if resp:
                try:
                    resp.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if reader_thread is None or not reader_thread.is_alive():
                self.server.gate.end_stream(token)


def create_managed_server(checkpoint: Callable[[dict], dict], restore: Callable[[dict], dict],
                          health_probe: Callable[[], bool], management_key: str, backend_key: str, storage_key: str,
                          *, operation_context: dict, upstream_port: int, host: str = "127.0.0.1",
                          port: int = 0, gate: OperationGate | None = None, upstream_timeout: float = 30.0, admission_probe: Callable[[], bool] | None = None) -> Any:
    if isinstance(upstream_timeout, bool) or not isinstance(upstream_timeout, (int, float)) or not math.isfinite(upstream_timeout) or not 0.05 <= upstream_timeout <= 30:
        raise ValueError("Invalid upstream timeout")
    if admission_probe is not None and not callable(admission_probe):
        raise ValueError("Invalid admission probe")
    if not callable(health_probe):
        raise ValueError("health_probe must be callable")
    if isinstance(upstream_port, bool) or not isinstance(upstream_port, int) or upstream_port < 1 or upstream_port > 65535:
        raise ValueError("upstream_port must be int in 1..65535")
    server = create_management_server(checkpoint, restore, management_key, backend_key, storage_key,
                                      operation_context=operation_context, host=host, port=port, gate=gate)
    bound_port = server.server_address[1]
    if bound_port == upstream_port:
        server.server_close()
        raise ValueError("Outer port collides with upstream port")
    server.RequestHandlerClass = _ManagedProxyHandler
    server.upstream_timeout = float(upstream_timeout)
    server.admission_probe = admission_probe if admission_probe is not None else (lambda: False)
    server.backend_key = backend_key
    server.health_probe = health_probe
    server.upstream_port = upstream_port
    return server

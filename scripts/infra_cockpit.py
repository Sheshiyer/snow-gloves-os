"""Infrastructure Cockpit Server.

Runs a ThreadingHTTPServer on 127.0.0.1.
Strict CORS, Host header checks, zero traceback leaks, and bounded query/body parsing.
"""

from __future__ import annotations

import argparse
import json
import socket
import http.client
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Semaphore
from typing import Any, Dict, Optional, Tuple
import urllib.parse

# Ensure scripts directory is in path for lib imports
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.cockpit_snapshot import build_snapshot, read_document, preview_plan

DEFAULT_PORT = 18761
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:18760",
    "http://localhost:18760",
)
MAX_REQUEST_BODY = 16 * 1024  # 16 KiB
MAX_QUERY_STRING = 1024       # 1024 chars
MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 4 MB
MAX_HEADER_BYTES = 32 * 1024  # 32 KiB
MAX_REQUESTLINE_BYTES = 4 * 1024  # 4 KiB
SOCKET_TIMEOUT = 2.0

def _parse_strict_json(body_raw: bytes) -> Dict[str, Any]:
    def _check_unique_keys(pairs):
        obj: Dict[str, Any] = {}
        for key, val in pairs:
            if key in obj:
                raise ValueError("duplicate_key")
            obj[key] = val
        return obj

    try:
        data = json.loads(
            body_raw.decode("utf-8"),
            object_pairs_hook=_check_unique_keys,
        )
    except Exception as err:
        raise ValueError("invalid_json") from err

    if not isinstance(data, dict):
        raise ValueError("json_not_object")
    return data

class CockpitServerHandler(BaseHTTPRequestHandler):
    server_version = "SnowglovesCockpit/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # Strict HTTP limits
    max_line = MAX_REQUESTLINE_BYTES
    max_headers = MAX_HEADER_BYTES

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setup(self) -> None:
        super().setup()
        if self.connection:
            self.connection.settimeout(SOCKET_TIMEOUT)

    def parse_request(self) -> bool:
        if len(self.raw_requestline) > MAX_REQUESTLINE_BYTES or b" //" in self.raw_requestline:
            self.requestline = ""
            self.request_version = "HTTP/1.1"
            self.command = None
            self.send_error(HTTPStatus.BAD_REQUEST)
            return False
        reader = self.rfile
        class BoundedHeaders:
            remaining = MAX_HEADER_BYTES
            def readline(bound, limit=-1):
                line = reader.readline(min(bound.remaining + 1, limit) if limit >= 0 else bound.remaining + 1)
                bound.remaining -= len(line)
                if bound.remaining < 0:
                    raise http.client.LineTooLong("headers")
                return line
        self.rfile = BoundedHeaders()
        try:
            return super().parse_request()
        finally:
            self.rfile = reader

    @property
    def cockpit_server(self) -> CockpitHTTPServer:
        return self.server  # type: ignore

    def _send_json(self, status: int, data: Dict[str, Any], origin: Optional[str] = None) -> None:
        try:
            body = json.dumps(data, indent=2).encode("utf-8")
            if len(body) > MAX_RESPONSE_BYTES:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "response_too_large", origin)
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def _send_error_json(self, status: int, code: str, origin: Optional[str] = None) -> None:
        self._send_json(status, {"error": code}, origin=origin)

    def _validate_headers_and_origin(self) -> Tuple[bool, Optional[str]]:
        headers_keys = [k.lower() for k in self.headers.keys()]

        # Reject duplicate critical headers
        if headers_keys.count("host") != 1:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_host_header")
            return False, None
        if headers_keys.count("origin") > 1:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_origin_header")
            return False, None
        if headers_keys.count("content-length") > 1:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length")
            return False, None
        if headers_keys.count("transfer-encoding") > 0 or headers_keys.count("expect") > 0:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "unsupported_header")
            return False, None

        # Content-Length canonical format validation if present
        if "content-length" in headers_keys:
            raw_cl = self.headers.get("Content-Length", "")
            if not raw_cl.isdigit() or (len(raw_cl) > 1 and raw_cl.startswith("0")):
                self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length")
                return False, None

        # Host verification
        host_val = self.headers.get("Host", "").strip()
        actual_port = self.cockpit_server.server_address[1]
        allowed_hosts = {
            f"127.0.0.1:{actual_port}",
            f"localhost:{actual_port}",
        }
        if host_val not in allowed_hosts:
            self._send_error_json(HTTPStatus.FORBIDDEN, "forbidden_host")
            return False, None

        # Origin verification
        origin_val = self.headers.get("Origin")
        validated_origin = None
        if origin_val is not None:
            origin_clean = origin_val.strip()
            if origin_clean not in self.cockpit_server.allowed_origins:
                self._send_error_json(HTTPStatus.FORBIDDEN, "forbidden_origin")
                return False, None
            validated_origin = origin_clean

        return True, validated_origin

    def _validate_and_parse_url(self, origin: Optional[str]) -> Tuple[bool, Optional[str], Optional[Dict[str, str]]]:
        # Reject absolute URLs, URL fragments, double slashes
        if "://" in self.path or self.path.startswith("//") or "#" in self.path:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_request_uri", origin)
            return False, None, None

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if not path.startswith("/") or "//" in path:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_path", origin)
            return False, None, None

        if len(parsed_url.query) > MAX_QUERY_STRING:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "query_too_long", origin)
            return False, None, None

        raw_query = parsed_url.query
        query_dict: Dict[str, str] = {}
        if raw_query:
            pairs = raw_query.split("&")
            for pair in pairs:
                if not pair or "=" not in pair:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_query_parameters", origin)
                    return False, None, None
                k, v = pair.split("=", 1)
                k_dec = urllib.parse.unquote_plus(k)
                v_dec = urllib.parse.unquote_plus(v)
                if not k_dec or not v_dec or k_dec in query_dict:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_query_parameters", origin)
                    return False, None, None
                query_dict[k_dec] = v_dec

        return True, path, query_dict

    def do_OPTIONS(self) -> None:
        try:
            valid, origin = self._validate_headers_and_origin()
            if not valid:
                return

            if not origin:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "origin_required_for_options")
                return

            valid_url, path, _ = self._validate_and_parse_url(origin)
            if not valid_url:
                return

            allowed_methods = {
                "/healthz": "GET, OPTIONS",
                "/api/infra/snapshot": "GET, OPTIONS",
                "/api/infra/document": "GET, OPTIONS",
                "/api/infra/plan": "POST, OPTIONS",
            }

            if path not in allowed_methods:
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", origin)
                return

            method = self.headers.get("Access-Control-Request-Method")
            if method is not None and method not in allowed_methods[path].split(", "):
                self._send_error_json(HTTPStatus.FORBIDDEN, "forbidden_method", origin)
                return

            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", allowed_methods[path])
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
        except Exception:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error")

    def do_GET(self) -> None:
        try:
            valid, origin = self._validate_headers_and_origin()
            if not valid:
                return

            # Check content length on GET (must be absent or 0)
            cl_header = self.headers.get("Content-Length")
            if cl_header is not None and cl_header.strip() != "0":
                self._send_error_json(HTTPStatus.BAD_REQUEST, "get_body_forbidden", origin)
                return

            valid_url, path, qs = self._validate_and_parse_url(origin)
            if not valid_url:
                return

            if path == "/healthz":
                if qs:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_query_parameters", origin)
                    return
                self._send_json(HTTPStatus.OK, {"status": "ok", "service": "infra_cockpit"}, origin)
                return

            if path == "/api/infra/snapshot":
                if not (set(qs.keys()) <= {"tenant"}):
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_query_parameters", origin)
                    return
                req_tenant = qs.get("tenant")
                if self.cockpit_server.configured_tenant:
                    if req_tenant and req_tenant != self.cockpit_server.configured_tenant:
                        self._send_error_json(HTTPStatus.FORBIDDEN, "tenant_scope_mismatch", origin)
                        return
                    effective_tenant = self.cockpit_server.configured_tenant
                else:
                    effective_tenant = req_tenant

                try:
                    snapshot = build_snapshot(
                        repo_root=self.cockpit_server.repo_root,
                        data_root=self.cockpit_server.data_root,
                        tenant=effective_tenant,
                        probe=self.cockpit_server.probe,
                    )
                    self._send_json(HTTPStatus.OK, snapshot, origin)
                except LookupError:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "tenant_not_found", origin)
                except ValueError:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_snapshot_request", origin)
                except Exception:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "snapshot_build_failed", origin)
                return

            if path == "/api/infra/document":
                if set(qs.keys()) != {"path"}:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "missing_path_parameter", origin)
                    return
                doc_path = qs["path"]
                try:
                    doc = read_document(self.cockpit_server.repo_root, doc_path)
                    self._send_json(HTTPStatus.OK, doc, origin)
                except (ValueError, FileNotFoundError):
                    self._send_error_json(HTTPStatus.NOT_FOUND, "document_not_found", origin)
                except Exception:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "document_read_failed", origin)
                return

            if path == "/api/infra/plan":
                self._send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", origin)
                return

            self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", origin)
        except Exception:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error")

    def do_POST(self) -> None:
        try:
            valid, origin = self._validate_headers_and_origin()
            if not valid:
                return

            valid_url, path, qs = self._validate_and_parse_url(origin)
            if not valid_url:
                return

            if qs:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "post_query_forbidden", origin)
                return

            if path in {"/healthz", "/api/infra/snapshot", "/api/infra/document"}:
                self._send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", origin)
                return

            if path != "/api/infra/plan":
                self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", origin)
                return

            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("application/json"):
                self._send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "invalid_content_type", origin)
                return

            cl_header = self.headers.get("Content-Length")
            if cl_header is None:
                self._send_error_json(HTTPStatus.LENGTH_REQUIRED, "missing_content_length", origin)
                return

            try:
                cl = int(cl_header)
            except ValueError:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_content_length", origin)
                return

            if cl < 0 or cl > MAX_REQUEST_BODY:
                self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large", origin)
                return

            try:
                body_raw = self.rfile.read(cl)
                if len(body_raw) != cl:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "incomplete_body", origin)
                    return
            except Exception:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "read_error", origin)
                return

            try:
                payload = _parse_strict_json(body_raw)
            except ValueError:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_json", origin)
                return

            if self.cockpit_server.configured_tenant:
                payload_tenant = payload.get("tenant")
                if payload_tenant is not None and payload_tenant != self.cockpit_server.configured_tenant:
                    self._send_error_json(HTTPStatus.FORBIDDEN, "tenant_scope_mismatch", origin)
                    return
                payload["tenant"] = self.cockpit_server.configured_tenant

            try:
                plan = preview_plan(
                    repo_root=self.cockpit_server.repo_root,
                    payload=payload,
                    data_root=self.cockpit_server.data_root,
                )
                self._send_json(HTTPStatus.OK, plan, origin)
            except LookupError:
                self._send_error_json(HTTPStatus.NOT_FOUND, "tenant_not_found", origin)
            except ValueError:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_plan_request", origin)
            except Exception:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "plan_preview_failed", origin)
        except Exception:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error")

    def _send_method_not_allowed(self) -> None:
        try:
            valid, origin = self._validate_headers_and_origin()
            self._send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", origin if valid else None)
        except Exception:
            self._send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed")

    def do_PUT(self) -> None:
        self._send_method_not_allowed()

    def do_DELETE(self) -> None:
        self._send_method_not_allowed()

    def do_PATCH(self) -> None:
        self._send_method_not_allowed()

    def do_HEAD(self) -> None:
        self._send_method_not_allowed()

    do_TRACE = do_HEAD
    do_CONNECT = do_HEAD

    def send_error(self, code: int, message: Optional[str] = None, explain: Optional[str] = None) -> None:
        # Override default BaseHTTPRequestHandler error page to avoid raw HTML and traceback leaks
        error_code_map = {
            HTTPStatus.BAD_REQUEST: "bad_request",
            HTTPStatus.REQUEST_URI_TOO_LONG: "request_uri_too_long",
            HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE: "request_header_fields_too_large",
            HTTPStatus.NOT_IMPLEMENTED: "not_implemented",
            HTTPStatus.METHOD_NOT_ALLOWED: "method_not_allowed",
        }
        err_msg = error_code_map.get(code, "bad_request" if code < 500 else "internal_error")
        self._send_error_json(code, err_msg)

    def log_message(self, format: str, *args: Any) -> None:
        pass

class CockpitHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        repo_root: Path,
        data_root: Optional[Path] = None,
        tenant: Optional[str] = None,
        probe: bool = True,
        allowed_origins: Tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS,
    ):
        self.repo_root = repo_root.resolve()
        self.data_root = data_root.resolve() if data_root else None
        self.configured_tenant = tenant
        self.probe = probe
        self.allowed_origins = allowed_origins
        self._sem = Semaphore(8)
        super().__init__(server_address, RequestHandlerClass)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._sem.acquire(blocking=False):
            try:
                # Bounded concurrency: reject with 503 before spawning worker thread
                con_sock = request
                if isinstance(con_sock, socket.socket):
                    body = json.dumps({"error": "server_busy"}, indent=2).encode("utf-8")
                    resp = (
                        f"HTTP/1.1 503 Service Unavailable\r\n"
                        f"Content-Type: application/json; charset=utf-8\r\n"
                        f"Content-Length: {len(body)}\r\n"
                        f"Cache-Control: no-store\r\n"
                        f"X-Content-Type-Options: nosniff\r\n"
                        f"Connection: close\r\n\r\n"
                    ).encode("utf-8") + body
                    con_sock.sendall(resp)
            except Exception:
                pass
            finally:
                self.close_request(request)
            return

        super().process_request(request, client_address)

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._sem.release()

def create_server(
    repo_root: Path,
    data_root: Optional[Path] = None,
    tenant: Optional[str] = None,
    port: int = DEFAULT_PORT,
    probe: bool = True,
    allowed_origins: Tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS,
) -> CockpitHTTPServer:
    if tenant is not None and (not isinstance(tenant, str) or re.fullmatch(r"[a-z0-9_][a-z0-9_-]{0,63}", tenant) is None):
        raise ValueError("invalid_tenant")
    server_addr = ("127.0.0.1", port)
    return CockpitHTTPServer(
        server_address=server_addr,
        RequestHandlerClass=CockpitServerHandler,
        repo_root=repo_root,
        data_root=data_root,
        tenant=tenant,
        probe=probe,
        allowed_origins=allowed_origins,
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="Snowgloves Infrastructure Cockpit Server")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--tenant", type=str, default=None)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-probe", action="store_true", default=False)
    parser.add_argument("--snapshot", action="store_true", default=False)
    args = parser.parse_args()

    if args.snapshot:
        snap = build_snapshot(
            repo_root=args.repo_root,
            data_root=args.data_root,
            tenant=args.tenant,
            probe=not args.no_probe,
        )
        print(json.dumps(snap, indent=2))
        return

    server = create_server(
        repo_root=args.repo_root,
        data_root=args.data_root,
        tenant=args.tenant,
        port=args.port,
        probe=not args.no_probe,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()

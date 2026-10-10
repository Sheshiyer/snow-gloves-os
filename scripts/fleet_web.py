#!/usr/bin/env python3
"""Production loopback static UI and bounded same-origin fleet proxy (stdlib)."""
import argparse
import http.client
import json
import mimetypes
from pathlib import Path
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 64 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
IDENT = r'[a-f0-9]{32}'


def fleet_route(method, path):
    reads = (r'/tasks', r'/tasks/' + IDENT + r'(?:/events|/artifact)?',
             r'/capabilities', r'/context', r'/approvals')
    writes = (r'/tasks', r'/tasks/' + IDENT + r'/(?:cancel|fanout)',
              r'/capabilities/execute', r'/approvals',
              r'/approvals/' + IDENT + r'/(?:approve|reject)')
    return any(re.fullmatch(p, path) for p in (reads if method == 'GET' else writes if method == 'POST' else ()))


def create_server(root, hosts, origins, port=18764, coordinator_port=4101, cockpit_port=18765, mcp_port=4103):
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not (root / 'index.html').is_file():
        raise ValueError('Built UI directory with index.html required')
    hosts = frozenset(hosts)
    origins = frozenset(origins)
    if not hosts or any(not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', h) for h in hosts):
        raise ValueError('Explicit hostnames required')
    for origin in origins:
        parts = urlsplit(origin)
        if parts.scheme not in ('http', 'https') or parts.netloc not in hosts or parts.path or parts.query or parts.fragment or parts.username:
            raise ValueError('Origins must match explicit hosts')

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(110)

        def log_message(self, *args):
            pass

        def reply(self, status, body, content_type='application/json', extra=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if extra:
                for k, v in extra.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def error(self, status, message):
            self.reply(status, json.dumps({'error': message}).encode())

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            if len(self.headers.get_all('Host', [])) != 1 or self.headers.get('Host') not in hosts:
                return self.error(403, 'Host unavailable')
            origin = self.headers.get('Origin')
            if len(self.headers.get_all('Origin', [])) > 1 or origin is not None and origin not in origins:
                return self.error(403, 'Origin unavailable')
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1 or self.headers.get('Expect'):
                return self.error(400, 'Unsupported framing')
            length = self.headers.get('Content-Length', '0')
            if not re.fullmatch(r'0|[1-9][0-9]{0,6}', length) or int(length) > MAX_BODY:
                return self.error(413, 'Body unavailable')
            if self.command == 'GET' and int(length):
                return self.error(400, 'GET body unavailable')
            if self.path.startswith('/api/'):
                return self.proxy(origin, int(length))
            if self.command != 'GET':
                return self.error(405, 'Method unavailable')
            parts = urlsplit(self.path)
            # Never normalize an encoded or traversing path into a valid asset.
            if '%' in parts.path or '\\' in parts.path or '..' in parts.path.split('/') or parts.path.startswith('//'):
                return self.error(404, 'Asset unavailable')
            leaf = 'index.html' if parts.path == '/' else parts.path.lstrip('/')
            target = root / leaf
            if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root):
                return self.error(404, 'Asset unavailable')
            if target.stat().st_size > MAX_RESPONSE:
                return self.error(413, 'Asset unavailable')
            return self.reply(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

        def proxy(self, origin, length):
            is_mcp = self.path == '/api/mcp'
            if is_mcp:
                if self.command != 'POST':
                    return self.error(405, 'Method unavailable')
                port, path = mcp_port, '/mcp'
            elif self.path.startswith('/api/fleet/'):
                if '?' in self.path or '#' in self.path or '%' in self.path:
                    return self.error(404, 'Route unavailable')
                path = self.path[len('/api/fleet'):]
                if not fleet_route(self.command, path):
                    return self.error(404, 'Route unavailable')
                port, path = coordinator_port, '/v1' + path
            elif self.path.startswith('/api/infra/'):
                parsed = urlsplit(self.path)
                if '#' in self.path or '%' in parsed.path:
                    return self.error(404, 'Route unavailable')
                if not (self.command == 'GET' and parsed.path in ('/api/infra/snapshot', '/api/infra/document') or self.command == 'POST' and parsed.path == '/api/infra/plan'):
                    return self.error(404, 'Route unavailable')
                port, path = cockpit_port, self.path
            else:
                return self.error(404, 'Route unavailable')
            if len(self.headers.get_all('Authorization', [])) > 1:
                return self.error(400, 'Invalid authorization')
            headers = {'Content-Type': 'application/json'}
            for name in ('Authorization', 'Origin', 'Accept', 'MCP-Protocol-Version'):
                if self.headers.get(name):
                    headers[name] = self.headers[name]
            payload = self.rfile.read(length) if length else None
            if length and len(payload) != length:
                return self.error(400, 'Incomplete body')
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=100)
            try:
                connection.request(self.command, path, body=payload, headers=headers)
                response = connection.getresponse()
                body = response.read(MAX_RESPONSE + 1)
                if len(body) > MAX_RESPONSE:
                    return self.error(502, 'Upstream response unavailable')
                # No redirects, cookies or upstream diagnostic bodies cross the boundary.
                if is_mcp and response.status in (202, 204):
                    return self.reply(response.status, body)
                if response.status != 200:
                    return self.error(response.status if response.status in (400,401,403,404,405,409,413,503) else 502, 'Fleet operation unavailable')
                return self.reply(200, body)
            except (OSError, http.client.HTTPException):
                return self.error(503, 'Fleet service unavailable')
            finally:
                connection.close()

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--host', action='append', required=True)
    p.add_argument('--origin', action='append', default=[])
    p.add_argument('--port', type=int, default=18764)
    p.add_argument('--coordinator-port', type=int, default=4101)
    p.add_argument('--cockpit-port', type=int, default=18765)
    p.add_argument('--mcp-port', type=int, default=4103)
    args = p.parse_args()
    server = create_server(args.root, args.host, args.origin, args.port, args.coordinator_port, args.cockpit_port, args.mcp_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

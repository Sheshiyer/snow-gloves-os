#!/usr/bin/env python3
"""Authenticated stateless HTTP MCP for the Grok Bot client-placed plugin."""
import argparse
import hmac
import json
from pathlib import Path


class ApplicationBoundary:
    """Authenticate before MCP parses the message; no browser cookies or sessions."""

    def __init__(self, app, token, hosts, origins):
        if not token or len(token) < 16 or any(c.isspace() for c in token):
            raise ValueError('Dedicated application credential required')
        self.app, self.token = app, token
        self.hosts, self.origins = set(hosts), set(origins)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = scope.get('headers', [])

        def values(name):
            return [v.decode('latin1') for k, v in headers if k.lower() == name]

        host, auth, origin = values(b'host'), values(b'authorization'), values(b'origin')
        status = None
        if len(host) != 1 or host[0] not in self.hosts or len(origin) > 1 or origin and origin[0] not in self.origins:
            status = 403
        elif scope.get('path') != '/mcp' or scope.get('query_string'):
            status = 404
        elif len(auth) != 1 or not hmac.compare_digest(auth[0], 'Bearer ' + self.token):
            status = 401
        elif scope.get('method') != 'POST':
            status = 405
        if status:
            body = json.dumps({'error': 'MCP access unavailable'}).encode()
            await send({'type': 'http.response.start', 'status': status,
                        'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store'),
                                    (b'content-length', str(len(body)).encode())]})
            return await send({'type': 'http.response.body', 'body': body})
        return await self.app(scope, receive, send)


def main():
    from fleet_mcp import FleetApi, create_server
    from mcp.server.transport_security import TransportSecuritySettings
    import uvicorn
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--token-file', required=True)
    p.add_argument('--endpoint', default='http://127.0.0.1:4101')
    p.add_argument('--port', type=int, default=4103)
    p.add_argument('--origin', action='append', default=[])
    args = p.parse_args()
    token_file = Path(args.token_file)
    if token_file.is_symlink() or not token_file.is_file() or token_file.stat().st_mode & 0o077:
        p.error('Application credential must be a private regular file')
    token = token_file.read_text().strip()
    hosts = [f'127.0.0.1:{args.port}', f'localhost:{args.port}']
    server = create_server(FleetApi(args.endpoint, token))
    app = server.streamable_http_app(json_response=True, stateless_http=True, max_request_body_size=64 * 1024,
                                    transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=args.origin))
    app = ApplicationBoundary(app, token, hosts, args.origin)
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()

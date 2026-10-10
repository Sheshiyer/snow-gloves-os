import http.client
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_web import create_server, fleet_route


@pytest.fixture
def web(tmp_path):
    (tmp_path / 'index.html').write_text('<h1>Fleet</h1>')
    (tmp_path / 'asset.js').write_text('console.log(1)')
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append((self.path, self.headers.get('Authorization'), self.headers.get('Origin')))
            data = json.dumps({'ok': True}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.do_GET()

    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    server = create_server(tmp_path, ['fleet.test'], ['https://fleet.test'], 0, upstream.server_port, upstream.server_port, upstream.server_port)
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (server, upstream)]
    for t in threads:
        t.start()

    def request(path, headers=None, method='GET', body=None):
        c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        c.request(method, path, body=body, headers={'Host': 'fleet.test', **(headers or {})})
        r = c.getresponse()
        result = r.status, r.read(), dict(r.getheaders())
        c.close()
        return result

    yield request, calls, tmp_path
    for s in (server, upstream):
        s.shutdown()
        s.server_close()
    for t in threads:
        t.join()


def test_static_host_origin_and_traversal(web):
    request, calls, root = web
    assert request('/')[0:2] == (200, b'<h1>Fleet</h1>')
    assert request('/?project=snowgloves')[0] == 200
    assert request('/asset.js')[0] == 200
    assert request('/', {'Host': 'evil.test'})[0] == 403
    assert request('/', {'Origin': 'https://evil.test'})[0] == 403
    for path in ('/../index.html', '/%2e%2e/index.html', '/.git/config'):
        assert request(path)[0] == 404
    (root / 'link').symlink_to(root / 'index.html')
    assert request('/link')[0] == 404
    assert not calls


def test_proxy_preserves_auth_origin_and_real_infra_path(web):
    request, calls, _ = web
    assert request('/api/fleet/context', {'Authorization': 'Bearer test-scope', 'Origin': 'https://fleet.test'})[0] == 200
    assert calls[-1] == ('/v1/context', 'Bearer test-scope', 'https://fleet.test')
    assert request('/api/infra/snapshot?tenant=heyzack')[0] == 200
    assert calls[-1][0] == '/api/infra/snapshot?tenant=heyzack'
    assert request('/api/infra/document?path=README.md')[0] == 200


def test_worker_management_and_framing_never_proxied(web):
    request, calls, _ = web
    for path in ('/api/fleet/worker/claim', '/api/fleet/tasks?owner=founder', '/api/fleet/../worker/claim', '/api/infra/unknown'):
        assert request(path)[0] == 404
    assert request('/api/fleet/tasks', {'Transfer-Encoding': 'chunked'})[0] == 400
    assert request('/api/fleet/tasks', {'Content-Length': '9999999'})[0] == 413
    assert not calls


def test_transport_allowlist_covers_only_reviewed_actions():
    tid = 'a' * 32
    assert fleet_route('GET', '/tasks/' + tid + '/artifact')
    assert fleet_route('POST', '/capabilities/execute')
    assert fleet_route('POST', '/approvals/' + tid + '/approve')
    assert not fleet_route('GET', '/worker/claim')
    assert not fleet_route('POST', '/service/restart')


def test_mcp_post_forwards_only_dedicated_transport_route(web):
    request, calls, _ = web
    assert request("/api/mcp", {"Authorization": "Bearer app-test", "Origin": "https://fleet.test", "Accept": "application/json, text/event-stream"}, method="POST", body="{} ")[0] == 200
    assert calls[-1] == ("/mcp", "Bearer app-test", "https://fleet.test")
    assert request("/api/mcp")[0] == 405
    assert request("/api/mcp?session=1", method="POST", body="{}")[0] == 404

"""Integration tests for Infrastructure Cockpit Server."""

import http.client
import gzip
import json
import threading
from pathlib import Path
import pytest
import yaml
import infra_cockpit

from lib.cockpit_snapshot import build_snapshot
from infra_cockpit import create_server
import socket


@pytest.mark.parametrize("headers,body,path", [
    ("Origin: http://127.0.0.1:18760\r\nOrigin: http://evil.test", b"{}", "/api/infra/plan"),
    ("Content-Length: 2", b"{}", "/api/infra/plan"),
    ("", b'{"tenant":"t1","tenant":"t2"}', "/api/infra/plan"),
    ("", b"[]", "/api/infra/plan"),
    ("", b"{}", "/api/infra/plan?tenant=t1"),
])
def test_http_ambiguous_input_rejected(server_fixture, headers, body, path):
    _, port, _ = server_fixture
    request = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
               f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
               f"{headers}\r\n\r\n").encode() + body
    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        conn.sendall(request)
        response = conn.recv(8192)
    assert b" 400 " in response.split(b"\r\n", 1)[0]


@pytest.mark.parametrize("path", ["/api/infra/snapshot?tenant=t1&tenant=t2", "/api/infra/snapshot?tenant=", "/api/infra/snapshot?tenant=..%2Fother"])
def test_snapshot_query_validation(server_fixture, path):
    _, port, _ = server_fixture
    assert _req(port, "GET", path)[0] == 400


def test_header_limit(server_fixture):
    _, port, _ = server_fixture
    with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
        conn.sendall((f"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Big: " + "a" * 34000 + "\r\n\r\n").encode())
        response = conn.recv(8192)
    assert b" 431 " in response.split(b"\r\n", 1)[0]


@pytest.fixture
def server_fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    # catalog
    (repo / "catalog").mkdir()
    (repo / "catalog" / "modules.json").write_text(json.dumps({
        "cards": [{"id": "m1", "status": "active", "risk": "low"}],
        "connectors": []
    }))

    # tenants
    t1 = repo / "tenants" / "t1"
    t1.mkdir(parents=True)
    (t1 / "MANIFEST.yaml").write_text(yaml.dump({"name": "Tenant One"}))
    (t1 / "enabled.yaml").write_text(yaml.dump({"modules": ["m1"]}))

    (repo / "README.md").write_text("# Server Test Doc")

    # Bind to port 0 for ephemeral testing port
    server = create_server(repo_root=repo, port=0, probe=False)
    port = server.server_address[1]

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    yield server, port, repo

    server.shutdown()
    server.server_close()


def _req(port: int, method: str, path: str, headers: dict = None, body: bytes = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
    h = {"Host": f"127.0.0.1:{port}"}
    if headers:
        h.update(headers)
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, resp.getheaders(), data


def test_healthz(server_fixture):
    _, port, _ = server_fixture
    st, _, data = _req(port, "GET", "/healthz")
    assert st == 200
    parsed = json.loads(data.decode("utf-8"))
    assert parsed.get("status") == "ok"


def test_host_validation(server_fixture):
    _, port, _ = server_fixture
    # Invalid host header
    st, _, _ = _req(port, "GET", "/healthz", headers={"Host": "evil.com:18761"})
    assert st == 403


def test_cors_origin_validation(server_fixture):
    _, port, _ = server_fixture
    # Allowed origin
    st, headers, _ = _req(port, "GET", "/healthz", headers={"Origin": "http://127.0.0.1:18760"})
    assert st == 200
    hdrs = dict(headers)
    assert hdrs.get("Access-Control-Allow-Origin") == "http://127.0.0.1:18760"

    # Disallowed origin
    st, _, _ = _req(port, "GET", "/healthz", headers={"Origin": "http://attacker.com"})
    assert st == 403


def test_options_preflight(server_fixture):
    _, port, _ = server_fixture
    st, headers, _ = _req(port, "OPTIONS", "/api/infra/plan", headers={"Origin": "http://127.0.0.1:18760"})
    assert st == 204
    hdrs = dict(headers)
    assert hdrs.get("Access-Control-Allow-Origin") == "http://127.0.0.1:18760"
    assert "POST, OPTIONS" in hdrs.get("Access-Control-Allow-Methods", "")


def test_snapshot_api(server_fixture):
    _, port, _ = server_fixture
    st, _, data = _req(port, "GET", "/api/infra/snapshot?tenant=t1")
    assert st == 200
    snap = json.loads(data.decode("utf-8"))
    assert snap["schema"] == "snowgloves.cockpit.v1"
    assert snap["scope"]["tenant"] == "t1"


def test_document_api(server_fixture):
    _, port, _ = server_fixture
    # Allowed doc
    st, _, data = _req(port, "GET", "/api/infra/document?path=README.md")
    assert st == 200
    doc = json.loads(data.decode("utf-8"))
    assert doc["path"] == "README.md"
    assert "# Server Test Doc" in doc["content"]

    # Disallowed doc
    st, _, _ = _req(port, "GET", "/api/infra/document?path=secret.txt")
    assert st == 404


def test_post_plan_api(server_fixture):
    _, port, _ = server_fixture
    body = json.dumps({
        "tenant": "t1",
        "title": "Implement login",
        "modules": ["m1"]
    }).encode("utf-8")

    st, _, data = _req(
        port, "POST", "/api/infra/plan",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        body=body
    )
    assert st == 200
    plan = json.loads(data.decode("utf-8"))
    assert plan["schema"] == "snowgloves.cockpit.plan.v1"
    assert plan["tenant"] == "t1"
    assert plan["modules"][0]["decision"] == "allowed"


def test_post_plan_bad_content_type(server_fixture):
    _, port, _ = server_fixture
    body = b"some text"
    st, _, _ = _req(
        port, "POST", "/api/infra/plan",
        headers={"Content-Type": "text/plain", "Content-Length": str(len(body))},
        body=body
    )
    assert st == 415


def test_post_plan_bad_json(server_fixture):
    _, port, _ = server_fixture
    body = b"not-valid-json"
    st, _, _ = _req(
        port, "POST", "/api/infra/plan",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        body=body
    )
    assert st == 400


def test_unsupported_methods(server_fixture):
    _, port, _ = server_fixture
    st, _, _ = _req(port, "DELETE", "/api/infra/snapshot")
    assert st == 405
    st, _, _ = _req(port, "PUT", "/api/infra/snapshot")
    assert st == 405
    st, _, _ = _req(port, "PATCH", "/api/infra/snapshot")
    assert st == 405


def test_query_length_bound(server_fixture):
    _, port, _ = server_fixture
    long_query = "tenant=" + ("a" * 2000)
    st, _, _ = _req(port, "GET", f"/api/infra/snapshot?{long_query}")
    assert st == 400


@pytest.fixture
def large_snapshot(server_fixture, monkeypatch):
    _, _, repo = server_fixture
    catalog = {'cards': [{'id': f'module-{i}', 'summary': 'Public catalog source context. ' * 100} for i in range(100)], 'connectors': []}
    (repo / 'catalog/modules.json').write_text(json.dumps(catalog))
    snapshot = build_snapshot(repo, tenant='t1', probe=False)
    # Freeze an actual source snapshot so identity and gzip byte comparison is exact.
    monkeypatch.setattr(infra_cockpit, 'build_snapshot', lambda **kwargs: snapshot)
    body = json.dumps(snapshot, indent=2).encode('utf-8')
    assert len(body) > 300_000
    return body


def test_large_snapshot_gzip_roundtrip_and_security_headers(server_fixture, large_snapshot):
    _, port, _ = server_fixture
    origin = 'http://127.0.0.1:18760'
    for encoding in ['gzip', 'br, gzip, deflate', 'GZip;q=1.000', 'identity;q=0, gzip;q=0.5']:
        status, headers, body = _req(port, 'GET', '/api/infra/snapshot?tenant=t1', headers={'Accept-Encoding': encoding, 'Origin': origin})
        hdrs = dict(headers)
        assert status == 200
        assert hdrs['Content-Encoding'] == 'gzip'
        assert int(hdrs['Content-Length']) == len(body)
        assert len(body) < len(large_snapshot) // 10
        assert gzip.decompress(body) == large_snapshot
        assert json.loads(gzip.decompress(body))['scope']['tenant'] == 't1'
        assert body[4:8] == b'\0\0\0\0'  # Stable gzip timestamp.
        assert hdrs['Cache-Control'] == 'no-store'
        assert hdrs['X-Content-Type-Options'] == 'nosniff'
        assert hdrs['Access-Control-Allow-Origin'] == origin
        assert [value for key, value in headers if key.lower() == 'vary'] == ['Origin, Accept-Encoding']
    _, _, repeat = _req(port, 'GET', '/api/infra/snapshot?tenant=t1', headers={'Accept-Encoding': 'gzip'})
    assert repeat == body


def test_identity_absent_zero_and_invalid_negotiation(server_fixture, large_snapshot):
    _, port, _ = server_fixture
    for encoding in ['', 'identity', 'br', '*', 'gzip;q=0', 'gzip;q=0.000, *;q=1', 'gzip;q=bad', 'gzip;q=NaN', 'gzip;q=-1', 'gzip;q=1.1', 'gzip;q=.5', 'gzip;q=0.1234', 'gzip;q=1;q=0', 'gzip;q=1, gzip;q=0', 'gzip;other=1', 'gzip, br;q=bad']:
        status, headers, body = _req(port, 'GET', '/api/infra/snapshot?tenant=t1', headers={'Accept-Encoding': encoding})
        assert status == 200
        assert 'Content-Encoding' not in dict(headers), encoding
        assert dict(headers)['Vary'] == 'Accept-Encoding'
        assert int(dict(headers)['Content-Length']) == len(body)
        assert body == large_snapshot
    # http.client normally supplies identity; omit the header explicitly as well.
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    conn.putrequest('GET', '/api/infra/snapshot?tenant=t1', skip_accept_encoding=True)
    conn.endheaders()
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader('Content-Encoding') is None
    assert response.read() == large_snapshot
    conn.close()


def test_small_json_stays_identity_and_raw_response_bound_precedes_compression(server_fixture, large_snapshot, monkeypatch):
    _, port, _ = server_fixture
    status, headers, body = _req(port, 'GET', '/healthz', headers={'Accept-Encoding': 'gzip'})
    assert status == 200
    assert 'Content-Encoding' not in dict(headers)
    assert json.loads(body)['status'] == 'ok'
    # A highly compressible payload still exceeds the raw response limit.
    compressed_size = len(gzip.compress(large_snapshot, mtime=0))
    monkeypatch.setattr(infra_cockpit, 'MAX_RESPONSE_BYTES', compressed_size + 100)
    status, headers, body = _req(port, 'GET', '/api/infra/snapshot?tenant=t1', headers={'Accept-Encoding': 'gzip'})
    assert status == 500
    assert json.loads(body) == {'error': 'response_too_large'}
    assert 'Content-Encoding' not in dict(headers)


def test_gzip_preserves_private_scope_pin_and_origin_denial(server_fixture, tmp_path):
    server, port, repo = server_fixture
    root = tmp_path / 'private'
    for slug in ('t1', 't2'):
        tenant = root / 'tenants' / slug
        tenant.mkdir(parents=True)
        (tenant / 'MANIFEST.yaml').write_text(f'name: {slug}\n')
    server.data_root = root
    server.configured_tenant = 't1'
    status, headers, body = _req(port, 'GET', '/api/infra/snapshot', headers={'Accept-Encoding': 'gzip', 'Origin': 'http://127.0.0.1:18760'})
    assert status == 200
    assert dict(headers)['Content-Encoding'] == 'gzip'
    snapshot = json.loads(gzip.decompress(body))
    assert snapshot['scope'] == {'mode': 'local-private', 'tenant': 't1', 'readOnly': True}
    assert [tenant['slug'] for tenant in snapshot['tenants']] == ['t1']
    status, _, body = _req(port, 'GET', '/api/infra/snapshot?tenant=t2', headers={'Accept-Encoding': 'gzip'})
    assert status == 403
    assert json.loads(body) == {'error': 'tenant_scope_mismatch'}
    status, headers, body = _req(port, 'GET', '/api/infra/snapshot', headers={'Accept-Encoding': 'gzip', 'Origin': 'http://attacker.com'})
    assert status == 403
    assert json.loads(body) == {'error': 'forbidden_origin'}
    assert 'Access-Control-Allow-Origin' not in dict(headers)
    assert dict(headers)['Cache-Control'] == 'no-store'

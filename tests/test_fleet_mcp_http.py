import asyncio
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_mcp_http import ApplicationBoundary


def test_authentication_host_origin_and_route_precede_mcp():
    called = []

    async def app(scope, receive, send):
        called.append(scope)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})

    boundary = ApplicationBoundary(app, 'dedicated-application-token', ['127.0.0.1:4103'], ['https://fleet.test'])

    def request(headers, path='/mcp', method='POST'):
        output = []

        async def send(message):
            output.append(message)

        async def receive():
            return {'type': 'http.request', 'body': b'{}'}

        scope = {'type': 'http', 'path': path, 'method': method, 'query_string': b'', 'headers': headers}
        asyncio.run(boundary(scope, receive, send))
        return output[0]['status']

    host = (b'host', b'127.0.0.1:4103')
    auth = (b'authorization', b'Bearer dedicated-application-token')
    assert request([host]) == 401
    assert request([host, auth, auth]) == 401
    assert request([(b'host', b'evil.test'), auth]) == 403
    assert request([host, auth, (b'origin', b'https://evil.test')]) == 403
    assert request([host, auth], '/worker/claim') == 404
    assert request([host, auth], method='GET') == 405
    assert not called
    assert request([host, auth, (b'origin', b'https://fleet.test')]) == 200
    assert len(called) == 1


TOKEN = 'dedicated-application-token'
HOST = (b'host', b'127.0.0.1:4103')
AUTH = (b'authorization', ('Bearer ' + TOKEN).encode())
ORIGIN = (b'origin', b'https://fleet.test')


def exercise_boundary(headers, *, path='/mcp', method='POST', query=b'', kind='http'):
    output, forwarded, consumed = [], [], []
    scope = {'type': kind, 'path': path, 'method': method,
             'query_string': query, 'headers': headers}

    async def receive():
        consumed.append(True)
        return {'type': 'http.request', 'body': b'{"private":"payload"}'}

    async def send(message):
        output.append(message)

    async def app(actual_scope, actual_receive, actual_send):
        forwarded.append((actual_scope, actual_receive, actual_send))
        await actual_send({'type': 'http.response.start', 'status': 204, 'headers': []})

    boundary = ApplicationBoundary(app, TOKEN, ['127.0.0.1:4103'], ['https://fleet.test'])
    asyncio.run(boundary(scope, receive, send))
    return scope, receive, send, output, forwarded, consumed


@pytest.mark.parametrize('headers,status', [
    ([AUTH], 403),
    ([HOST, HOST, AUTH], 403),
    ([HOST, (b'Host', b'127.0.0.1:4103'), AUTH], 403),
    ([(b'host', b'evil.test'), AUTH], 403),
    ([HOST, AUTH, ORIGIN, ORIGIN], 403),
    ([HOST, AUTH, ORIGIN, (b'Origin', b'https://fleet.test')], 403),
    ([HOST, AUTH, (b'origin', b'null')], 403),
    ([HOST, AUTH, (b'origin', b'https://fleet.test.evil')], 403),
    ([HOST], 401),
    ([HOST, AUTH, AUTH], 401),
    ([HOST, AUTH, (b'Authorization', AUTH[1])], 401),
    ([HOST, (b'authorization', b'Bearer incorrect-token')], 401),
    ([HOST, (b'authorization', b'')], 401),
    ([HOST, (b'authorization', TOKEN.encode())], 401),
    ([HOST, (b'authorization', ('Basic ' + TOKEN).encode())], 401),
    ([HOST, (b'authorization', ('Bearer ' + TOKEN + ' ').encode())], 401),
])
def test_denied_headers_do_not_reach_or_read_mcp(headers, status):
    _, _, _, output, forwarded, consumed = exercise_boundary(headers)
    assert output[0]['status'] == status
    assert not forwarded
    assert not consumed
    assert len(output) == 2
    response_headers = dict(output[0]['headers'])
    body = output[1]['body']
    assert response_headers[b'cache-control'] == b'no-store'
    assert response_headers[b'content-type'] == b'application/json'
    assert int(response_headers[b'content-length']) == len(body)
    assert json.loads(body) == {'error': 'MCP access unavailable'}
    assert TOKEN.encode() not in body
    assert b'payload' not in body


@pytest.mark.parametrize('route,status', [
    ({'path': '/worker/claim'}, 404),
    ({'path': '/api/mcp'}, 404),
    ({'path': '/mcp/'}, 404),
    ({'query': b'token=private-value'}, 404),
    ({'method': 'GET'}, 405),
    ({'method': 'OPTIONS'}, 405),
    ({'method': 'DELETE'}, 405),
])
def test_denied_routes_have_generic_uncacheable_response(route, status):
    _, _, _, output, forwarded, consumed = exercise_boundary([HOST, AUTH], **route)
    assert output[0]['status'] == status
    assert not forwarded and not consumed
    assert dict(output[0]['headers'])[b'cache-control'] == b'no-store'
    assert json.loads(output[1]['body']) == {'error': 'MCP access unavailable'}
    assert b'private-value' not in output[1]['body']


@pytest.mark.parametrize('headers', [
    [HOST, AUTH],
    [HOST, AUTH, ORIGIN],
    [(b'Host', HOST[1]), (b'Authorization', AUTH[1]), (b'Origin', ORIGIN[1])],
])
def test_authorized_requests_preserve_asgi_scope_and_callbacks(headers):
    scope, receive, send, output, forwarded, consumed = exercise_boundary(headers)
    assert len(forwarded) == 1
    assert forwarded[0][0] is scope
    assert forwarded[0][1] is receive
    assert forwarded[0][2] is send
    assert output == [{'type': 'http.response.start', 'status': 204, 'headers': []}]
    assert not consumed


@pytest.mark.parametrize('kind', ['lifespan', 'websocket'])
def test_non_http_scopes_are_forwarded_without_http_authentication(kind):
    scope, receive, send, _, forwarded, consumed = exercise_boundary([], kind=kind)
    assert len(forwarded) == 1
    assert forwarded[0][0] is scope
    assert forwarded[0][1] is receive
    assert forwarded[0][2] is send
    assert not consumed


@pytest.mark.parametrize('token', ['', 'short', 'a' * 15, 'a' * 16 + ' ', 'a' * 16 + '\n'])
def test_invalid_application_credentials_are_rejected_at_construction(token):
    with pytest.raises(ValueError, match='Dedicated application credential required'):
        ApplicationBoundary(None, token, ['127.0.0.1:4103'], [])

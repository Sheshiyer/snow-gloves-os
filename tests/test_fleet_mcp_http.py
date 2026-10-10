import asyncio
from pathlib import Path
import sys

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

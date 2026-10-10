import io
import json
from email.message import Message
from pathlib import Path
import sys
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fleet_grok_client as client

TOKEN = 'synthetic-secret-do-not-print'


def config():
    return {'mcpServers': {'snowgloves-fleet': {'type': 'http', 'placement': 'client',
            'url': 'https://fleet.example/api/mcp', 'headers': {'Authorization': 'Bearer ' + TOKEN}}}}


def private_file(tmp_path, value=None):
    path = tmp_path / 'import.json'
    path.write_text(json.dumps(value or config()))
    path.chmod(0o600)
    return path


def test_private_regular_owned_file(tmp_path):
    path = private_file(tmp_path)
    assert client.load_import(path)['placement'] == 'client'
    path.chmod(0o644)
    with pytest.raises(client.ClientError):
        client.load_import(path)
    path.chmod(0o600)
    link = tmp_path / 'link'
    link.symlink_to(path)
    with pytest.raises(client.ClientError):
        client.load_import(link)
    with pytest.raises(client.ClientError):
        client.load_import(tmp_path)


@pytest.mark.parametrize('url', ['http://fleet.example/api/mcp', 'https://fleet.example/mcp',
    'https://user:secret@fleet.example/api/mcp', 'https://fleet.example/api/mcp?token=secret',
    'https://fleet.example/api/mcp#fragment', 'https://fleet.example:bad/api/mcp',
    'https://fleet.example\n/api/mcp'])
def test_rejects_unsafe_destinations(tmp_path, url):
    data = config()
    data['mcpServers']['snowgloves-fleet']['url'] = url
    with pytest.raises(client.ClientError):
        client.load_import(private_file(tmp_path, data))


@pytest.mark.parametrize('change', ['multiple', 'placement', 'header', 'newline', 'command'])
def test_rejects_unexpected_import_shapes(tmp_path, change):
    data = config()
    server = data['mcpServers']['snowgloves-fleet']
    if change == 'multiple':
        data['mcpServers']['other'] = dict(server)
    elif change == 'placement':
        server['placement'] = 'server'
    elif change == 'header':
        server['headers']['X-Other'] = 'value'
    elif change == 'newline':
        server['headers']['Authorization'] += '\nX: value'
    else:
        server['command'] = 'sh'
    with pytest.raises(client.ClientError):
        client.load_import(private_file(tmp_path, data))


class Response(io.BytesIO):
    def __init__(self, payload, status=200, content_type='application/json', session=None):
        super().__init__(json.dumps(payload).encode() if not isinstance(payload, bytes) else payload)
        self.status = status
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        if session:
            self.headers['Mcp-Session-Id'] = session


class Opener:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def initialized():
    return Response({'jsonrpc': '2.0', 'id': 1, 'result': {'protocolVersion': '2025-03-26'}}, session='safe-session')


def test_discovery_only_session_pagination_and_no_secret_output():
    opener = Opener([initialized(), Response(b'', 202),
        Response({'jsonrpc': '2.0', 'id': 2, 'result': {'tools': [{'name': TOKEN}], 'nextCursor': 'next'}}),
        Response({'jsonrpc': '2.0', 'id': 3, 'result': {'tools': [{'name': 'task_submit'}]}})])
    result = client.probe(next(iter(config()['mcpServers'].values())), opener=opener)
    assert result['tool_count'] == 2
    assert result['scope'] == 'transport-only'
    assert not result['app_registration_verified']
    assert TOKEN not in json.dumps(result)
    methods = [json.loads(req.data)['method'] for req, _ in opener.calls]
    assert methods == ['initialize', 'notifications/initialized', 'tools/list', 'tools/list']
    assert opener.calls[1][0].get_header('Mcp-session-id') == 'safe-session'
    assert json.loads(opener.calls[3][0].data)['params'] == {'cursor': 'next'}


@pytest.mark.parametrize('response', [Response(b'bad json'), Response(b'x' * (client.MAX_BYTES + 1)),
    Response({}, status=302), Response({}, content_type='text/event-stream'),
    Response({'jsonrpc': '2.0', 'id': 99, 'result': {}}),
    Response({'jsonrpc': '2.0', 'id': 1, 'error': {'message': TOKEN}}),
    urllib.error.URLError(TOKEN)])
def test_remote_errors_are_bounded_and_redacted(response):
    with pytest.raises(client.ClientError) as caught:
        client.probe(next(iter(config()['mcpServers'].values())), opener=Opener([response]))
    assert TOKEN not in str(caught.value)


def test_redirect_refused_and_environment_proxy_disabled(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY', 'http://unexpected.example:1234')
    opener = client.make_opener()
    assert not any(isinstance(h, client.urllib.request.ProxyHandler) and h.proxies for h in opener.handlers)
    with pytest.raises(client.ClientError):
        client.NoRedirect().redirect_request(None, None, 302, TOKEN, {}, 'https://elsewhere.example')


@pytest.mark.parametrize('timeout', [0, -1, 31, float('nan'), float('inf')])
def test_timeout_bound(timeout):
    with pytest.raises(client.ClientError):
        client.probe(next(iter(config()['mcpServers'].values())), timeout=timeout)


def test_cli_validation_never_discloses_import(tmp_path, capsys):
    assert client.main([str(private_file(tmp_path))]) == 0
    assert TOKEN not in capsys.readouterr().out
    assert client.main([str(tmp_path / TOKEN)]) == 1
    assert TOKEN not in capsys.readouterr().out


@pytest.mark.parametrize('url', [42, None, {}, []])
def test_non_string_url_fails_safely(tmp_path, url):
    data = config()
    data['mcpServers']['snowgloves-fleet']['url'] = url
    with pytest.raises(client.ClientError):
        client.load_import(private_file(tmp_path, data))


def test_duplicate_pagination_cursor_fails_safely():
    opener = Opener([initialized(), Response(b'', 202),
        Response({'jsonrpc': '2.0', 'id': 2, 'result': {'tools': [], 'nextCursor': TOKEN}}),
        Response({'jsonrpc': '2.0', 'id': 3, 'result': {'tools': [], 'nextCursor': TOKEN}})])
    with pytest.raises(client.ClientError) as caught:
        client.probe(next(iter(config()['mcpServers'].values())), opener=opener)
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize('token', ['short', 'REPLACE_IN_PRIVATE_IMPORT_FILE'])
def test_rejects_short_or_template_credentials(tmp_path, token):
    data = config()
    data['mcpServers']['snowgloves-fleet']['headers']['Authorization'] = 'Bearer ' + token
    with pytest.raises(client.ClientError):
        client.load_import(private_file(tmp_path, data))


@pytest.mark.parametrize('raw', [
    '{"mcpServers":{},"mcpServers":{}}',
    '{"mcpServers":{"one":{},"one":{}}}',
    '{"mcpServers":{"one":{"headers":{"Authorization":"first","Authorization":"last"}}}}',
])
def test_rejects_duplicate_keys_at_every_depth(tmp_path, raw):
    path = private_file(tmp_path)
    path.write_text(raw)
    with pytest.raises(client.ClientError):
        client.load_import(path)

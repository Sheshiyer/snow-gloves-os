#!/usr/bin/env python3
"""Validate a private Grok import and probe MCP discovery without running tools.

This transport check does not establish Grok Bot UI registration or task acceptance.
"""
import argparse
import json
import math
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


class ClientError(Exception):
    """Safe errors whose messages never contain remote data or credentials."""


def load_import(path):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
            raise ClientError('Import must be an owned regular file with mode 0600.')
        if info.st_size > MAX_BYTES:
            raise ClientError('Import exceeds size limit.')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ClientError('Import exceeds size limit.')
        data = json.loads(raw, object_pairs_hook=unique_object)
        servers = data['mcpServers']
        if set(data) != {'mcpServers'} or not isinstance(servers, dict) or len(servers) != 1:
            raise ValueError()
        server = next(iter(servers.values()))
        if set(server) != {'type', 'url', 'headers', 'placement'}:
            raise ValueError()
        if server['type'] != 'http' or server['placement'] != 'client':
            raise ValueError()
        url = server['url']
        if not isinstance(url, str):
            raise ValueError()
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.path != '/api/mcp'
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or any(c.isspace() for c in url)
                or any(ord(c) < 32 for c in url)):
            raise ValueError()
        _ = parsed.port  # Reject malformed ports before network use.
        headers = server['headers']
        if not isinstance(headers, dict) or set(headers) != {'Authorization'}:
            raise ValueError()
        auth = headers['Authorization']
        if (not isinstance(auth, str) or not re.fullmatch(r'Bearer [A-Za-z0-9._~+/=-]{16,}', auth)
                or 'REPLACE_IN_PRIVATE_IMPORT_FILE' in auth):
            raise ValueError()
        return server
    except ClientError:
        raise
    except (OSError, ValueError, TypeError, KeyError, StopIteration, AttributeError, RecursionError):
        raise ClientError('Invalid or inaccessible private import.') from None
    finally:
        if fd is not None:
            os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('MCP redirects are refused.')


def make_opener():
    # Explicitly disable environment proxies: bearer credentials go only to the import URL.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def probe(server, timeout=10, opener=None):
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ClientError('Timeout must be greater than zero and at most 30 seconds.')
    opener = opener or make_opener()
    session = None

    def post(payload, notification=False):
        nonlocal session
        headers = {'Authorization': server['headers']['Authorization'],
                   'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': '2025-03-26'}
        if session:
            headers['Mcp-Session-Id'] = session
        request = urllib.request.Request(server['url'], json.dumps(payload).encode(), headers, method='POST')
        try:
            with opener.open(request, timeout=timeout) as response:
                if response.status not in ((200, 202, 204) if notification else (200,)):
                    raise ClientError('MCP returned an unexpected HTTP status.')
                next_session = response.headers.get('Mcp-Session-Id')
                if next_session is not None:
                    if not re.fullmatch(r'[\x21-\x7e]{1,256}', next_session):
                        raise ClientError('MCP returned an invalid session header.')
                    session = next_session
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ClientError('MCP response exceeds size limit.')
                if notification:
                    return None
                if response.headers.get_content_type() != 'application/json':
                    raise ClientError('MCP probe requires a JSON response.')
                body = json.loads(raw, object_pairs_hook=unique_object)
                if (not isinstance(body, dict) or body.get('jsonrpc') != '2.0'
                        or body.get('id') != payload['id'] or 'error' in body
                        or not isinstance(body.get('result'), dict)):
                    raise ClientError('MCP returned an invalid discovery response.')
                return body['result']
        except ClientError:
            raise
        except Exception:
            # urllib exceptions may include URLs, headers or attacker-controlled bodies.
            raise ClientError('MCP transport or JSON discovery failed.') from None

    result = post({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                   'params': {'protocolVersion': '2025-03-26', 'capabilities': {},
                              'clientInfo': {'name': 'snowgloves-grok-probe', 'version': '1'}}})
    if result.get('protocolVersion') != '2025-03-26':
        raise ClientError('MCP protocol version is unsupported.')
    post({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, notification=True)
    count = 0
    cursor = None
    seen = set()
    for page in range(20):
        result = post({'jsonrpc': '2.0', 'id': page + 2, 'method': 'tools/list',
                       'params': {'cursor': cursor} if cursor else {}})
        tools = result.get('tools')
        if not isinstance(tools, list) or any(not isinstance(t, dict) or not isinstance(t.get('name'), str) for t in tools):
            raise ClientError('MCP returned an invalid tool list.')
        count += len(tools)
        cursor = result.get('nextCursor')
        if cursor is None:
            return {'ok': True, 'scope': 'transport-only', 'tool_count': count,
                    'app_registration_verified': False, 'task_execution_verified': False}
        if not isinstance(cursor, str) or not cursor or cursor in seen or len(cursor) > 4096:
            raise ClientError('MCP returned an invalid pagination cursor.')
        seen.add(cursor)
    raise ClientError('MCP discovery exceeds page limit.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('import_file')
    parser.add_argument('--probe', action='store_true', help='Run initialize and tools/list only (at most 20 discovery pages)')
    parser.add_argument('--timeout', type=float, default=10, help='Per-request socket timeout in seconds, maximum 30')
    args = parser.parse_args(argv)
    try:
        server = load_import(args.import_file)
        result = probe(server, args.timeout) if args.probe else {
            'ok': True, 'scope': 'import-validation-only', 'app_registration_verified': False}
        print(json.dumps(result))
        return 0
    except ClientError as error:
        print(json.dumps({'ok': False, 'scope': 'transport-only', 'error': str(error)}))
        return 1


if __name__ == '__main__':
    sys.exit(main())

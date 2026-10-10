"""scripts/fleet_tasks.py sends the operator token only to a loopback coordinator endpoint."""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import fleet_tasks  # noqa: E402


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setenv('SNOWGLOVES_FLEET_TOKEN', 'operator-synthetic-token')
    monkeypatch.setattr(fleet_tasks.urllib.request, 'urlopen',
                        lambda request, timeout: calls.append(request) or Response(b'{}'))
    return calls


@pytest.mark.parametrize('endpoint', [
    'http://attacker.example', 'https://127.0.0.1:4101', 'http://127.0.0.1.attacker.example:4101',
    'http://user:pw@127.0.0.1:4101', 'http://127.0.0.1:4101/v1', 'http://127.0.0.1:4101?x=1',
    'http://10.0.0.5:4101', 'http://127.0.0.1:99999', 'not a url',
])
def test_non_loopback_endpoints_are_refused_before_any_request(sent, monkeypatch, endpoint):
    monkeypatch.setattr(sys, 'argv', ['fleet_tasks.py', '--endpoint', endpoint, 'list'])
    with pytest.raises(SystemExit) as error:
        fleet_tasks.main()
    assert error.value.code == 2
    assert sent == []


@pytest.mark.parametrize('endpoint', ['http://127.0.0.1:4101', 'http://localhost:4101/', 'http://127.0.0.1'])
def test_loopback_endpoints_carry_the_token(sent, monkeypatch, endpoint):
    monkeypatch.setattr(sys, 'argv', ['fleet_tasks.py', '--endpoint', endpoint, 'list'])
    assert fleet_tasks.main() == 0
    assert len(sent) == 1
    assert sent[0].full_url == endpoint.rstrip('/') + '/v1/tasks'
    assert sent[0].get_header('Authorization') == 'Bearer operator-synthetic-token'

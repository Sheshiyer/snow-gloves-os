"""The fleet MCP server is a thin, loopback-only client of the coordinator; it enforces nothing itself."""
import asyncio
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_mcp import FleetApi, FleetError, create_server
from lib.fleet_coordinator import server as make_server
from test_fleet_coordinator import fleet  # noqa: F401  (fixture)


@pytest.fixture
def api(fleet):
    c, conf, _ = fleet
    http = make_server(c, 0)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield FleetApi('http://127.0.0.1:%d' % http.server_port, conf['principals']['founder']['token']), c, conf
    http.shutdown()
    http.server_close()


def test_rejects_non_loopback_endpoints_and_bad_tokens():
    for endpoint in ('https://127.0.0.1:4101', 'http://example.com:4101', 'http://127.0.0.1:4101/x', 'http://u:p@127.0.0.1:4101'):
        with pytest.raises(ValueError):
            FleetApi(endpoint, 'token')
    for token in ('', '  ', 'a\nb'):
        with pytest.raises(ValueError):
            FleetApi('http://127.0.0.1:4101', token)


def test_submit_status_logs_list_and_cancel_round_trip(api):
    fleet_api, _, _ = api
    task = fleet_api.submit(project='snowgloves', brief='Review the code', title='T')
    assert task['status'] == 'queued' and task['access'] == 'read'
    assert [t['id'] for t in fleet_api.list()] == [task['id']]
    assert fleet_api.status(task['id'])['id'] == task['id']
    assert fleet_api.logs(task['id']) == []
    assert fleet_api.cancel(task['id'])['status'] == 'cancelled'


def test_graph_options_pass_through_and_the_parent_shows_the_graph(api):
    fleet_api, _, _ = api
    parent = fleet_api.submit(project='snowgloves', brief='Plan')
    kid = fleet_api.submit(project='snowgloves', brief='Verify', parent_id=parent['id'], logical_role='sentinel', stage='verify')
    assert (kid['parent_id'], kid['logical_role'], kid['stage']) == (parent['id'], 'sentinel', 'verify')
    assert [k['id'] for k in fleet_api.status(parent['id'])['graph']['children']] == [kid['id']]


def test_identical_submissions_are_idempotent_unless_a_key_is_given(api):
    fleet_api, _, _ = api
    one = fleet_api.submit(project='snowgloves', brief='X', idempotency_key='k')
    assert fleet_api.submit(project='snowgloves', brief='X', idempotency_key='k')['id'] == one['id']
    assert fleet_api.submit(project='snowgloves', brief='X')['id'] != one['id']


def test_coordinator_refusals_surface_as_errors_with_the_safe_message(api):
    fleet_api, _, _ = api
    with pytest.raises(FleetError) as exc:
        fleet_api.submit(project='private', brief='X')
    assert '403' in str(exc.value) and 'Project unavailable' in str(exc.value)
    parent = fleet_api.submit(project='snowgloves', brief='Plan')
    with pytest.raises(FleetError) as exc:
        fleet_api.submit(project='snowgloves', brief='W', parent_id=parent['id'], logical_role='cto', access='write')
    assert 'Write access unavailable' in str(exc.value)


def test_bad_task_ids_never_reach_the_network(api):
    fleet_api, _, _ = api
    for bad in ('../tasks', 'abc', 'a' * 31 + '/events', ''):
        with pytest.raises(ValueError):
            fleet_api.status(bad)
        with pytest.raises(ValueError):
            fleet_api.cancel(bad)
        with pytest.raises(ValueError):
            fleet_api.fanout(bad)


def test_fanout_posts_an_empty_object_and_surfaces_coordinator_errors(api, monkeypatch):
    fleet_api, _, _ = api
    calls = []

    def call(method, path, body=None):
        calls.append((method, path, body))
        return {'plan_id': 'b' * 32, 'root_id': 'a' * 32, 'children': []}

    monkeypatch.setattr(fleet_api, 'call', call)
    assert fleet_api.fanout('a' * 32)['root_id'] == 'a' * 32
    assert calls == [('POST', '/v1/tasks/' + 'a' * 32 + '/fanout', {})]

    def refused(*_args, **_kwargs):
        raise FleetError('Coordinator refused the request (HTTP 403): Fanout unavailable')

    monkeypatch.setattr(fleet_api, 'call', refused)
    with pytest.raises(FleetError, match='403'):
        fleet_api.fanout('a' * 32)


def test_wrong_token_is_reported_without_leaking_it(fleet):
    c, conf, _ = fleet
    http = make_server(c, 0)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        with pytest.raises(FleetError) as exc:
            FleetApi('http://127.0.0.1:%d' % http.server_port, 'not-the-token').list()
        assert '401' in str(exc.value) and 'not-the-token' not in str(exc.value)
    finally:
        http.shutdown()
        http.server_close()


def test_mcp_server_registers_fleet_tools_and_delegates_fanout(api, monkeypatch):
    pytest.importorskip('mcp.server')
    fleet_api, _, _ = api
    server_ = create_server(fleet_api)
    tools = asyncio.run(server_.list_tools())
    assert sorted(t.name for t in tools) == sorted(['fleet_cancel', 'fleet_fanout', 'fleet_list', 'fleet_logs', 'fleet_status', 'fleet_submit',
        'fleet_context', 'fleet_capabilities', 'fleet_artifact', 'fleet_execute_capability', 'fleet_approvals',
        'fleet_request_approval', 'fleet_approve', 'fleet_reject'])
    submit = next(t for t in tools if t.name == 'fleet_submit')
    assert {'project', 'brief', 'parent_id', 'logical_role', 'stage', 'supersedes', 'access'} <= set(submit.input_schema['properties'])
    result = asyncio.run(server_.call_tool('fleet_submit', {'project': 'snowgloves', 'brief': 'via mcp'}))
    assert 'queued' in json.dumps(result, default=str)
    with pytest.raises(ValueError, match='32-character'):
        FleetApi.fanout(fleet_api, '../bad')
    calls = []
    monkeypatch.setattr(fleet_api, 'fanout', lambda task_id: calls.append(task_id) or {
        'plan_id': 'b' * 32, 'root_id': task_id, 'children': [],
    })
    result = asyncio.run(server_.call_tool('fleet_fanout', {'task_id': 'a' * 32}))
    assert calls == ['a' * 32]
    assert 'plan_id' in json.dumps(result, default=str)


def test_context_capabilities_and_approvals_use_same_authenticated_http_scope(api):
    fleet_api, _, _ = api
    context = fleet_api.context()
    assert [item['id'] for item in context['projects']] == ['snowgloves']
    assert context['permissions'] == ['read', 'submit', 'cancel']
    assert fleet_api.capabilities()  # disabled catalog visibility requires no enabled tenant
    assert fleet_api.approvals() == []
    with pytest.raises(FleetError, match='409'):
        fleet_api.execute_capability('snowgloves', 'ms-copywriting', {}, 'request-one')
    with pytest.raises(FleetError, match='403'):
        fleet_api.decide_approval('a' * 32, True)
    with pytest.raises(FleetError, match='404'):
        fleet_api.artifact('a' * 32)


def test_new_tools_only_forward_declared_arguments_and_keep_submission_keys(api, monkeypatch):
    fleet_api, _, _ = api
    calls = []
    monkeypatch.setattr(fleet_api, 'call', lambda method, path, body=None: calls.append((method, path, body)) or {'artifact': {}, 'task': {}, 'approval': {}})
    fleet_api.execute_capability('snowgloves', 'review', {'focus': 'a'}, 'stable-key', approval_id='a' * 32, worker_id='coding-02')
    fleet_api.request_approval('snowgloves', 'review', {'focus': 'a'}, 'stable-approval', worker_id='coding-02')
    fleet_api.decide_approval('a' * 32, False)
    fleet_api.artifact('b' * 32)
    assert calls == [
        ('POST', '/v1/capabilities/execute', {'project': 'snowgloves', 'capability_id': 'review', 'inputs': {'focus': 'a'}, 'idempotency_key': 'stable-key', 'approval_id': 'a' * 32, 'worker_id': 'coding-02'}),
        ('POST', '/v1/approvals', {'project': 'snowgloves', 'capability_id': 'review', 'inputs': {'focus': 'a'}, 'idempotency_key': 'stable-approval', 'worker_id': 'coding-02'}),
        ('POST', '/v1/approvals/' + 'a' * 32 + '/reject', {}),
        ('GET', '/v1/tasks/' + 'b' * 32 + '/artifact', None)]
    with pytest.raises(ValueError):
        fleet_api.decide_approval('../bad', True)
    with pytest.raises(ValueError):
        fleet_api.artifact('../bad')

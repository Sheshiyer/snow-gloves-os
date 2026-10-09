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


def test_mcp_server_registers_exactly_the_fleet_tools(api):
    pytest.importorskip('mcp.server')
    fleet_api, _, _ = api
    server_ = create_server(fleet_api)
    tools = asyncio.run(server_.list_tools())
    assert sorted(t.name for t in tools) == ['fleet_cancel', 'fleet_list', 'fleet_logs', 'fleet_status', 'fleet_submit']
    submit = next(t for t in tools if t.name == 'fleet_submit')
    assert {'project', 'brief', 'parent_id', 'logical_role', 'stage', 'supersedes', 'access'} <= set(submit.input_schema['properties'])
    result = asyncio.run(server_.call_tool('fleet_submit', {'project': 'snowgloves', 'brief': 'via mcp'}))
    assert 'queued' in json.dumps(result, default=str)

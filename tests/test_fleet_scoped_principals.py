"""Scoped principals: an observer reads the owner's tasks but can neither create nor change anything."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from lib.fleet_coordinator import Rejected, load_config
from lib.fleet_coordinator import server as make_server
from test_fleet_coordinator import claim, fleet, report, submit  # noqa: F401  (fleet is a fixture)
from test_fleet_task_graph import child, finish


OBSERVER = {'token': 'observer-token-0123456789', 'projects': ['snowgloves'], 'permissions': ['read'], 'view_owners': ['founder']}


@pytest.fixture
def observed(fleet):
    c, conf, now = fleet
    conf['principals']['gary'] = dict(OBSERVER)
    return c, conf, conf['principals']['founder'], conf['principals']['gary']


def test_observer_lists_and_reads_the_owners_tasks_including_graph_and_events(observed):
    c, conf, founder, gary = observed
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    kid = child(c, conf, parent, 'sentinel')
    assert {t['id'] for t in c.list_tasks('gary', gary)} == {parent['id'], kid['id']}
    detail = c.detail('gary', gary, parent['id'])
    assert detail['graph']['children'][0]['id'] == kid['id']
    assert isinstance(c.detail('gary', gary, parent['id'], events=True), list)


def test_observer_cannot_submit_cancel_or_write(observed):
    c, conf, founder, gary = observed
    task = submit(c, conf)
    body = {'project': 'snowgloves', 'brief': 'x', 'runtime': 'codex', 'idempotency_key': 'g1'}
    with pytest.raises(Rejected) as exc:
        c.submit('gary', gary, body)
    assert exc.value.status == 403
    with pytest.raises(Rejected) as exc:
        c.cancel('gary', gary, task['id'])
    assert exc.value.status == 403
    assert c.detail('founder', founder, task['id'])['status'] == 'queued'


def test_fanout_requires_submit_and_owner_before_the_planner_runs(fleet):
    c, conf, _ = fleet
    conf['projects']['snowgloves']['fanout'] = True
    reader = {
        'token': 'reader-token-0123456789',
        'projects': ['snowgloves'],
        'permissions': ['read', 'submit'],
        'fanout_projects': ['snowgloves'],
    }
    observer = {
        'token': 'observer-fanout-token-0123456789',
        'projects': ['snowgloves'],
        'permissions': ['read'],
        'view_owners': ['reader'],
        # An accidental capability grant must not turn viewing into mutation.
        'fanout_projects': ['snowgloves'],
    }
    conf['principals'].update(reader=reader, observer=observer)
    root = c.submit('reader', reader, {
        'project': 'snowgloves', 'brief': 'Read only root', 'runtime': 'codex',
        'idempotency_key': 'reader-root',
    })
    calls = []
    c._plan_from_hermes = lambda value: calls.append(value) or {'children': [
        {'logical_role': 'librarian', 'stage': 'reference', 'title': 'References', 'brief': 'Read.'},
        {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Verify', 'brief': 'Verify.'},
    ]}

    reader['permissions'] = ['read']  # Own task, but read-only principals cannot plan.
    with pytest.raises(Rejected) as exc:
        c.fanout('reader', reader, root['id'])
    assert exc.value.status == 403
    with pytest.raises(Rejected) as exc:
        c.fanout('observer', observer, root['id'])
    assert exc.value.status == 403
    assert calls == []

    observer['permissions'] = ['read', 'submit']
    with pytest.raises(Rejected) as exc:
        c.fanout('observer', observer, root['id'])
    assert exc.value.status == 404  # view_owners never supplies owner mutation.
    assert calls == []

    reader['permissions'] = ['read', 'submit']
    accepted = c.fanout('reader', reader, root['id'])
    assert len(accepted['children']) == 2
    assert len(calls) == 1


def test_viewing_never_grants_mutation_even_with_all_permissions(observed):
    c, conf, founder, gary = observed
    gary['permissions'] = ['read', 'submit', 'cancel']
    task = submit(c, conf)
    with pytest.raises(Rejected) as exc:
        c.cancel('gary', gary, task['id'])  # allowed to cancel, but not someone else's task
    assert exc.value.status == 404
    parent = submit(c, conf, idempotency_key='p2')
    with pytest.raises(Rejected) as exc:  # cannot attach children to the owner's task
        c.submit('gary', gary, {'project': 'snowgloves', 'brief': 'x', 'runtime': 'codex', 'idempotency_key': 'g2',
                                'parent_id': parent['id'], 'logical_role': 'sentinel'})
    assert exc.value.status == 404


def test_observer_is_limited_to_its_projects(observed):
    c, conf, founder, gary = observed
    task = submit(c, conf)
    gary['projects'] = []
    assert c.list_tasks('gary', gary) == []
    with pytest.raises(Rejected) as exc:
        c.detail('gary', gary, task['id'])
    assert exc.value.status == 404


def test_observer_sees_only_the_owners_it_is_granted(observed):
    c, conf, founder, gary = observed
    submit(c, conf)
    gary['view_owners'] = []
    assert c.list_tasks('gary', gary) == []


def test_a_principal_without_the_new_fields_keeps_its_old_behaviour(fleet):
    c, conf, _ = fleet
    founder = conf['principals']['founder']
    assert 'permissions' not in founder and 'view_owners' not in founder
    task = submit(c, conf)
    assert c.detail('founder', founder, task['id'])['id'] == task['id']
    assert c.cancel('founder', founder, task['id'])['status'] == 'cancelled'


def test_read_permission_is_required_to_read(observed):
    c, conf, founder, gary = observed
    gary['permissions'] = []
    for call in (lambda: c.list_tasks('gary', gary), lambda: c.detail('gary', gary, 'a' * 32)):
        with pytest.raises(Rejected) as exc:
            call()
        assert exc.value.status == 403


def _config(tmp_path, principal):
    repo = tmp_path / 'repo'
    (repo / '.git').mkdir(parents=True)
    path = tmp_path / 'coordinator.json'
    path.write_text(json.dumps({'data_root': str(tmp_path / 'ops'),
        'projects': {'snowgloves': {'root': str(repo), 'tenant': 't', 'organization': 'o', 'runtimes': ['codex']}},
        'principals': {'founder': {'token': 'founder-token-0123456789', 'projects': ['snowgloves']}, 'gary': principal},
        'workers': {}}))
    path.chmod(0o600)
    return path


@pytest.mark.parametrize('bad', [
    {'permissions': ['read', 'root']},
    {'permissions': 'read'},
    {'view_owners': ['nobody']},
    {'view_owners': 'founder'},
])
def test_config_rejects_unknown_permissions_and_owners(tmp_path, bad):
    with pytest.raises(ValueError):
        load_config(_config(tmp_path, {**OBSERVER, **bad}))


def test_config_accepts_the_observer_shape(tmp_path):
    assert load_config(_config(tmp_path, dict(OBSERVER)))['principals']['gary']['permissions'] == ['read']


def test_observer_over_http_reads_but_cannot_write(observed):
    c, conf, founder, gary = observed
    task = submit(c, conf)
    conf['projects']['snowgloves']['fanout'] = True
    gary['fanout_projects'] = ['snowgloves']
    http = make_server(c, 0)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d' % http.server_port

    def call(method, path, body=None, token=gary['token']):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
    try:
        assert call('GET', '/v1/tasks')[1]['tasks'][0]['id'] == task['id']
        assert call('GET', '/v1/tasks/' + task['id'])[0] == 200
        assert call('POST', '/v1/tasks', {'project': 'snowgloves', 'brief': 'x', 'idempotency_key': 'h1'})[0] == 403
        assert call('POST', '/v1/tasks/%s/cancel' % task['id'], {})[0] == 403
        assert call('POST', '/v1/tasks/%s/fanout' % task['id'], {})[0] == 403
        assert call('GET', '/v1/tasks', token='wrong-token-0123456789')[0] == 401
    finally:
        http.shutdown()
        http.server_close()

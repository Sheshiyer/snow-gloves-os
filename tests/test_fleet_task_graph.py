"""Parent/child task graph: authoritative transitions live in the coordinator; no scheduler."""
import hashlib

import pytest

from lib.fleet_coordinator import Rejected
from test_fleet_coordinator import claim, fleet, report, submit  # noqa: F401  (fleet is a fixture)


def child(c, conf, parent, role, key=None, **updates):
    return submit(c, conf, parent_id=parent['id'], logical_role=role, stage='review',
                  idempotency_key=key or 'child-' + role, **updates)


def finish(c, conf, task_id, name='out.json'):
    """Run one queued task to a verified artifact."""
    running = claim(c, conf)
    assert running['id'] == task_id
    artifact = c.artifacts / (task_id + '-' + name)
    artifact.write_text('{"ok": true}')
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    report(c, conf, running, type='succeeded', artifact={'path': str(artifact), 'sha256': digest})


def test_child_inherits_scope_and_carries_parent_role_and_stage(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    kid = child(c, conf, parent, 'librarian')
    assert (kid['parent_id'], kid['logical_role'], kid['stage']) == (parent['id'], 'librarian', 'review')
    assert (kid['project'], kid['runtime']) == ('snowgloves', 'codex')
    assert parent['parent_id'] is None


@pytest.mark.parametrize('updates', [
    {'logical_role': 'janitor'},
    {'stage': 'ship-it'},
    {'parent_id': 'f' * 32},
])
def test_invalid_child_requests_are_rejected(fleet, updates):
    c, conf, _ = fleet
    parent = submit(c, conf)
    body = {'parent_id': parent['id'], 'logical_role': 'cto', 'stage': 'plan'}
    body.update(updates)
    with pytest.raises(Rejected) as exc:
        submit(c, conf, idempotency_key='bad', **body)
    assert exc.value.status in (400, 404)


def test_role_or_stage_without_parent_is_rejected(fleet):
    c, conf, _ = fleet
    for extra in ({'logical_role': 'sentinel'}, {'stage': 'verify'}):
        with pytest.raises(Rejected) as exc:
            submit(c, conf, idempotency_key='orphan', **extra)
        assert exc.value.status == 400


def test_graph_is_one_level_and_bounded(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    kid = child(c, conf, parent, 'cto')
    with pytest.raises(Rejected) as exc:
        child(c, conf, kid, 'sentinel', key='grandchild')
    assert exc.value.status == 409
    for index in range(6):
        child(c, conf, parent, 'dispatcher', key='fill-%d' % index)
    with pytest.raises(Rejected) as exc:
        child(c, conf, parent, 'dispatcher', key='one-too-many')
    assert exc.value.status == 409


def test_cannot_add_children_to_a_terminal_parent(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    c.cancel('founder', conf['principals']['founder'], parent['id'])
    with pytest.raises(Rejected) as exc:
        child(c, conf, parent, 'cto')
    assert exc.value.status == 409


def test_idempotency_key_cannot_move_a_child_between_parents_or_roles(fleet):
    c, conf, _ = fleet
    first = submit(c, conf, idempotency_key='p1')
    second = submit(c, conf, idempotency_key='p2')
    original = child(c, conf, first, 'cto', key='same')
    assert child(c, conf, first, 'cto', key='same')['id'] == original['id']
    for other in (lambda: child(c, conf, second, 'cto', key='same'), lambda: child(c, conf, first, 'sentinel', key='same')):
        with pytest.raises(Rejected) as exc:
            other()
        assert exc.value.status == 409


def test_cancelling_parent_cascades_to_open_children_only(fleet):
    c, conf, _ = fleet
    principal = conf['principals']['founder']
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    done = child(c, conf, parent, 'librarian')
    finish(c, conf, done['id'])
    queued = child(c, conf, parent, 'cto')
    c.cancel('founder', principal, parent['id'])
    assert c.detail('founder', principal, queued['id'])['status'] == 'cancelled'
    assert c.detail('founder', principal, done['id'])['status'] == 'succeeded'


def test_cancelling_a_running_parent_requests_cancel_and_cancels_queued_children(fleet):
    c, conf, _ = fleet
    principal = conf['principals']['founder']
    parent = submit(c, conf)
    running = claim(c, conf)
    kid = child(c, conf, parent, 'cto')
    c.cancel('founder', principal, parent['id'])
    assert c.detail('founder', principal, parent['id'])['status'] == 'cancel_requested'
    assert c.detail('founder', principal, kid['id'])['status'] == 'cancelled'
    assert running['id'] == parent['id']


def test_parent_detail_rolls_up_children_without_extra_state(fleet):
    c, conf, _ = fleet
    principal = conf['principals']['founder']
    parent = submit(c, conf)
    assert c.detail('founder', principal, parent['id'])['graph'] == {'children': [], 'status': 'none'}
    kid = child(c, conf, parent, 'librarian')
    graph = c.detail('founder', principal, parent['id'])['graph']
    assert graph['status'] == 'incomplete'
    assert [(k['id'], k['logical_role'], k['status']) for k in graph['children']] == [(kid['id'], 'librarian', 'queued')]


def test_graph_is_verified_only_when_sentinel_succeeded_with_an_artifact(fleet):
    c, conf, _ = fleet
    principal = conf['principals']['founder']
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    lib = child(c, conf, parent, 'librarian')
    finish(c, conf, lib['id'])
    assert c.detail('founder', principal, parent['id'])['graph']['status'] == 'incomplete'  # no sentinel yet
    sentinel = child(c, conf, parent, 'sentinel', key='sentinel')
    assert c.detail('founder', principal, parent['id'])['graph']['status'] == 'incomplete'
    finish(c, conf, sentinel['id'])
    assert c.detail('founder', principal, parent['id'])['graph']['status'] == 'verified'


def test_a_failed_child_blocks_verification(fleet):
    c, conf, _ = fleet
    principal = conf['principals']['founder']
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    lib = child(c, conf, parent, 'librarian')
    running = claim(c, conf)
    report(c, conf, running, type='failed', message='boom')
    sentinel = child(c, conf, parent, 'sentinel', key='sentinel')
    finish(c, conf, sentinel['id'])
    assert lib['id'] == running['id']
    assert c.detail('founder', principal, parent['id'])['graph']['status'] == 'failed'


def test_list_exposes_parent_id_so_the_board_can_group(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    kid = child(c, conf, parent, 'cto')
    rows = {t['id']: t for t in c.list_tasks('founder', conf['principals']['founder'])}
    assert rows[kid['id']]['parent_id'] == parent['id'] and rows[parent['id']]['parent_id'] is None


def failed_child(c, conf, parent, role='sentinel', key=None):
    kid = child(c, conf, parent, role, key=key)
    running = claim(c, conf)
    assert running['id'] == kid['id']
    report(c, conf, running, type='failed', message='gateway 429')
    return kid


def retry(c, conf, parent, original, role='sentinel', key=None, **updates):
    return child(c, conf, parent, role, key=key or 'retry-' + original['id'][:6], supersedes=original['id'], **updates)


def graph(c, conf, parent):
    return c.detail('founder', conf['principals']['founder'], parent['id'])['graph']


def test_retry_replaces_a_failed_child_and_graph_can_verify(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    bad = failed_child(c, conf, parent)
    assert graph(c, conf, parent)['status'] == 'failed'
    good = retry(c, conf, parent, bad)
    assert good['supersedes'] == bad['id']
    assert graph(c, conf, parent)['status'] == 'incomplete'
    finish(c, conf, good['id'])
    g = graph(c, conf, parent)
    assert g['status'] == 'verified'
    rows = {k['id']: k for k in g['children']}
    assert rows[bad['id']]['superseded_by'] == good['id'] and rows[good['id']]['superseded_by'] is None


@pytest.mark.parametrize('state', ['queued', 'succeeded', 'interrupted', 'cancelled'])
def test_only_failed_children_can_be_superseded(fleet, state):
    c, conf, now = fleet
    principal = conf['principals']['founder']
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    kid = child(c, conf, parent, 'sentinel')
    if state == 'succeeded':
        finish(c, conf, kid['id'])
    elif state == 'interrupted':
        claim(c, conf)
        now[0] += 10_000
        c.list_tasks('founder', principal)  # lease expiry marks it interrupted
    elif state == 'cancelled':
        c.cancel('founder', principal, kid['id'])
    with pytest.raises(Rejected) as exc:
        retry(c, conf, parent, kid)
    assert exc.value.status == 409
    assert c.detail('founder', principal, kid['id'])['status'] == state


def test_retry_must_match_parent_role_and_be_unique(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    bad = failed_child(c, conf, parent)
    other = submit(c, conf, idempotency_key='other-root')
    with pytest.raises(Rejected) as exc:
        retry(c, conf, parent, bad, role='librarian')
    assert exc.value.status == 409
    with pytest.raises(Rejected) as exc:
        child(c, conf, other, 'sentinel', key='cross', supersedes=bad['id'])
    assert exc.value.status == 409
    with pytest.raises(Rejected) as exc:
        child(c, conf, parent, 'sentinel', key='ghost', supersedes='e' * 32)
    assert exc.value.status == 404
    with pytest.raises(Rejected) as exc:
        submit(c, conf, idempotency_key='noparent', supersedes=bad['id'])
    assert exc.value.status == 400
    retry(c, conf, parent, bad, key='first')
    with pytest.raises(Rejected) as exc:
        retry(c, conf, parent, bad, key='second')
    assert exc.value.status == 409


def test_retry_chain_is_bounded_and_replay_is_idempotent(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    first = failed_child(c, conf, parent)
    second = retry(c, conf, parent, first, key='r1')
    assert retry(c, conf, parent, first, key='r1')['id'] == second['id']
    running = claim(c, conf)
    report(c, conf, running, type='failed')
    third = retry(c, conf, parent, second, key='r2')
    running = claim(c, conf)
    report(c, conf, running, type='failed')
    with pytest.raises(Rejected) as exc:
        retry(c, conf, parent, third, key='r3')
    assert exc.value.status == 409


def test_retries_do_not_consume_the_child_limit(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    bad = failed_child(c, conf, parent)
    retry(c, conf, parent, bad)
    for index in range(6):
        child(c, conf, parent, 'dispatcher', key='fill-%d' % index)
    with pytest.raises(Rejected):
        child(c, conf, parent, 'dispatcher', key='over')

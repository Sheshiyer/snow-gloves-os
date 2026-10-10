"""Write access is default-off and only granted to explicit, graph-scoped CTO children."""
import pytest

from lib.fleet_coordinator import Rejected
from test_fleet_coordinator import claim, fleet, submit  # noqa: F401  (fleet is a fixture)
from test_fleet_task_graph import finish


def enable(conf, project=True, principal=True):
    conf['projects']['snowgloves']['write'] = project
    conf['principals']['founder']['write_projects'] = ['snowgloves'] if principal else []


def writer(c, conf, parent, **updates):
    body = dict(parent_id=parent['id'], logical_role='cto', stage='review', access='write', idempotency_key='w1')
    body.update(updates)
    return submit(c, conf, **body)


def test_tasks_default_to_read_access(fleet):
    c, conf, _ = fleet
    assert submit(c, conf)['access'] == 'read'


@pytest.mark.parametrize('project,principal', [(False, True), (True, False), (False, False)])
def test_write_needs_project_flag_and_principal_grant(fleet, project, principal):
    c, conf, _ = fleet
    parent = submit(c, conf)
    enable(conf, project, principal)
    with pytest.raises(Rejected) as exc:
        writer(c, conf, parent)
    assert exc.value.status == 403


def test_write_is_off_when_nothing_is_configured(fleet):
    c, conf, _ = fleet
    parent = submit(c, conf)
    with pytest.raises(Rejected) as exc:
        writer(c, conf, parent)
    assert exc.value.status == 403


def test_write_requires_a_cto_graph_child(fleet):
    c, conf, _ = fleet
    enable(conf)
    parent = submit(c, conf)
    with pytest.raises(Rejected) as exc:
        submit(c, conf, access='write', idempotency_key='root-write')
    assert exc.value.status == 400
    for role in ('sentinel', 'librarian', 'ceo', 'interpreter', 'chief-of-staff', 'dispatcher'):
        with pytest.raises(Rejected) as exc:
            writer(c, conf, parent, logical_role=role, idempotency_key='r-' + role)
        assert exc.value.status == 403, role


def test_invalid_access_value_is_rejected(fleet):
    c, conf, _ = fleet
    enable(conf)
    parent = submit(c, conf)
    for bad in ('admin', 1, True, ['write']):
        with pytest.raises(Rejected) as exc:
            writer(c, conf, parent, access=bad, idempotency_key='bad-%s' % bad)
        assert exc.value.status == 400


def test_granted_write_child_is_visible_to_the_worker_claim(fleet):
    c, conf, _ = fleet
    enable(conf)
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    task = writer(c, conf, parent)
    assert (task['access'], task['logical_role'], task['parent_id']) == ('write', 'cto', parent['id'])
    assert claim(c, conf)['access'] == 'write'


def test_access_is_part_of_the_idempotency_digest(fleet):
    c, conf, _ = fleet
    enable(conf)
    parent = submit(c, conf)
    first = writer(c, conf, parent)
    assert writer(c, conf, parent)['id'] == first['id']
    with pytest.raises(Rejected) as exc:
        writer(c, conf, parent, access='read')
    assert exc.value.status == 409


def test_read_children_are_unchanged_when_write_is_enabled(fleet):
    c, conf, _ = fleet
    enable(conf)
    parent = submit(c, conf)
    kid = submit(c, conf, parent_id=parent['id'], logical_role='sentinel', stage='verify', idempotency_key='k')
    assert kid['access'] == 'read'


def test_a_retry_cannot_change_access(fleet):
    c, conf, _ = fleet
    enable(conf)
    parent = submit(c, conf)
    finish(c, conf, parent['id'], name='parent.json')
    first = writer(c, conf, parent)
    running = claim(c, conf)
    from test_fleet_coordinator import report
    report(c, conf, running, type='failed')
    with pytest.raises(Rejected) as exc:
        writer(c, conf, parent, access='read', supersedes=first['id'], idempotency_key='downgrade')
    assert exc.value.status == 409
    assert writer(c, conf, parent, supersedes=first['id'], idempotency_key='same')['supersedes'] == first['id']

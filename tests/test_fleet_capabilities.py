"""Real coordinator boundaries for catalog visibility, dispatch, approval and artifacts."""
import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from lib import paths
from lib.fleet_coordinator import Coordinator, Rejected
from test_fleet_coordinator import fleet  # noqa: F401


@pytest.fixture
def capabilities(fleet, tmp_path, monkeypatch):
    c, config, clock = fleet
    root, data = tmp_path / 'code', tmp_path / 'data'
    (root / 'catalog').mkdir(parents=True)
    (root / 'skills/review').mkdir(parents=True)
    skill = root / 'skills/review/SKILL.md'
    skill.write_text('# Reviewed skill\nRead project documentation and return three source references.\n')
    monkeypatch.setattr(paths, '_CODE_ROOT', root)
    monkeypatch.setenv('SNOWGLOVES_DATA', str(data))
    catalog = {'cards': [
        {'id': 'review', 'name': 'Project review', 'kind': 'skill', 'risk': 'low', 'approval': 'no', 'disposition': 'add'},
        {'id': 'gated', 'name': 'Gated review', 'kind': 'skill', 'risk': 'high', 'approval': 'yes', 'disposition': 'pointer'},
        {'id': 'off', 'kind': 'skill', 'risk': 'low', 'disposition': 'add'},
        {'id': 'held', 'kind': 'skill', 'risk': 'low', 'disposition': 'hold'},
        {'id': 'refused', 'kind': 'skill', 'risk': 'low', 'disposition': 'refuse'},
        {'id': 'no-adapter', 'kind': 'skill', 'risk': 'low', 'disposition': 'add'},
    ], 'connectors': [{'id': 'gmail', 'capabilities': [{'id': 'gmail.read_messages', 'risk': 'low', 'approval': 'no'}]}]}
    (root / 'catalog/modules.json').write_text(json.dumps(catalog))
    entry = {'adapter': 'reviewed_skill', 'skill_path': 'skills/review/SKILL.md',
             'skill_sha256': hashlib.sha256(skill.read_bytes()).hexdigest(),
             'runtime': 'codex', 'input_schema': {'type': 'object', 'additionalProperties': False,
                                                'properties': {'focus': {'type': 'string', 'maxLength': 80}}, 'required': ['focus']}}
    registry = {'schema': 'snowgloves.capability-registry.v1', 'entries': {'review': dict(entry), 'gated': dict(entry)}}
    (root / 'catalog/execution-registry.json').write_text(json.dumps(registry))
    tenant = data / 'tenants/heyzack'
    tenant.mkdir(parents=True)
    enabled = tenant / 'enabled.yaml'
    enabled.write_text('schema: snowgloves.enabled.v1\ntenant: heyzack\nmodules:\n' + ''.join('  - id: %s\n' % name for name in ('review', 'gated', 'held', 'refused', 'no-adapter', 'gmail.read_messages')))
    config['workers']['mac-coding-1']['node_id'] = 'coding-01'
    config['workers']['wrong-worker']['node_id'] = 'coding-02'
    config['principals']['approver'] = {'token': 'approval-token', 'projects': ['snowgloves'], 'permissions': ['read', 'approve']}
    c.claim('mac-coding-1', config['workers']['mac-coding-1'])  # authenticated observed polling
    return c, config, clock, root, enabled


def body(**updates):
    value = {'project': 'snowgloves', 'capability_id': 'review', 'inputs': {'focus': 'documentation'}, 'idempotency_key': 'one'}
    value.update(updates)
    return value


def execute(ctx, **updates):
    c, config, *_ = ctx
    return c.capabilities.execute('founder', config['principals']['founder'], body(**updates))


def request(ctx, **updates):
    c, config, *_ = ctx
    return c.capabilities.request_approval('founder', config['principals']['founder'], body(capability_id='gated', **updates))['approval']


def approve(ctx, ident, who='approver', payload=None):
    c, config, *_ = ctx
    return c.capabilities.decide(who, config['principals'][who], ident, 'approved', {} if payload is None else payload)['approval']


def test_all_catalog_entries_visible_and_readiness_is_live(capabilities):
    c, config, clock, *_ = capabilities
    items = {item['id']: item for item in c.capabilities.list(config['principals']['founder'])['capabilities']}
    assert set(items) == {'review', 'gated', 'off', 'held', 'refused', 'no-adapter', 'gmail', 'gmail.read_messages'}
    assert {key: items[key]['state'] for key in ('review', 'gated', 'off', 'held', 'refused', 'no-adapter', 'gmail.read_messages')} == {
        'review': 'executable', 'gated': 'approval_required', 'off': 'disabled', 'held': 'refused',
        'refused': 'refused', 'no-adapter': 'unsupported', 'gmail.read_messages': 'unsupported'}
    clock[0] += 61
    ready = c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'review')
    assert ready['state'] == 'unsupported' and 'recently polled' in ready['reason']
    c.claim('mac-coding-1', config['workers']['mac-coding-1'])
    assert c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'review')['state'] == 'executable'


def test_context_has_scope_permissions_no_roots_or_tokens(capabilities):
    c, config, *_ = capabilities
    value = c.capabilities.context(config['principals']['founder'])
    assert value['permissions'] == ['read', 'submit', 'cancel']
    assert value['projects'][0]['workers'][0]['availability'] == 'observed'
    assert 'token' not in json.dumps(value) and 'root' not in json.dumps(value)
    assert c.capabilities.context(config['principals']['outsider']) == {'projects': [], 'permissions': ['read', 'submit', 'cancel']}


@pytest.mark.parametrize('ident', ['off', 'held', 'refused', 'no-adapter', 'gmail.read_messages', 'missing'])
def test_unavailable_capabilities_never_dispatch(capabilities, ident):
    c, *_ = capabilities
    with pytest.raises(Rejected):
        execute(capabilities, capability_id=ident)
    assert c.db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_scope_permission_and_command_fields_are_server_enforced(capabilities):
    c, config, *_ = capabilities
    for data in (body(project='private'), dict(body(), command='touch /tmp/x'), dict(body(), root='/tmp')):
        with pytest.raises(Rejected):
            c.capabilities.execute('founder', config['principals']['founder'], data)
    with pytest.raises(Rejected):
        c.capabilities.execute('outsider', config['principals']['outsider'], body())
    with pytest.raises(Rejected):
        c.capabilities.execute('approver', config['principals']['approver'], body())
    assert c.db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


@pytest.mark.parametrize('inputs', [{'focus': 'x', 'command': 'id'}, {}, {'focus': 1}, {'focus': 'x' * 81}, ['x']])
def test_inputs_are_declared_bounded_and_typed(capabilities, inputs):
    with pytest.raises(Rejected):
        execute(capabilities, inputs=inputs)


def test_source_pin_and_activation_rechecked_at_execution(capabilities):
    c, config, _, root, enabled = capabilities
    assert c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'review')['state'] == 'executable'
    (root / 'skills/review/SKILL.md').write_text('Changed after review')
    with pytest.raises(Rejected):
        execute(capabilities)
    assert c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'review')['state'] == 'missing_configuration'
    enabled.unlink()
    assert c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'review')['state'] == 'disabled'


def test_registry_cannot_execute_outside_skills_or_fabricate_connector(capabilities, tmp_path):
    c, config, _, root, _ = capabilities
    path = root / 'catalog/execution-registry.json'
    reg = json.loads(path.read_text())
    outside = tmp_path / 'secret.md'
    outside.write_text('outside')
    reg['entries']['review']['skill_path'] = str(outside)
    reg['entries']['review']['skill_sha256'] = hashlib.sha256(outside.read_bytes()).hexdigest()
    reg['entries']['gmail.read_messages'] = reg['entries']['gated']
    path.write_text(json.dumps(reg))
    for ident in ('review', 'gmail.read_messages'):
        with pytest.raises(Rejected):
            execute(capabilities, capability_id=ident)
    assert c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'gmail.read_messages')['state'] == 'unsupported'


def test_execution_idempotent_durable_and_selected_worker_only(capabilities):
    c, config, clock, *_ = capabilities
    result = execute(capabilities, worker_id='mac-coding-1')
    tid = result['task']['id']
    assert result['task']['requested_worker'] == 'mac-coding-1'
    assert execute(capabilities, worker_id='mac-coding-1')['task']['id'] == tid
    with pytest.raises(Rejected):
        execute(capabilities, inputs={'focus': 'changed'}, worker_id='mac-coding-1')
    second = Coordinator(config, clock=lambda: clock[0])
    try:
        assert second.capabilities.execute('founder', config['principals']['founder'], body(worker_id='mac-coding-1'))['task']['id'] == tid
        assert second.claim('wrong-worker', config['workers']['wrong-worker']) is None
        task = second.claim('mac-coding-1', config['workers']['mac-coding-1'])
        assert task['id'] == tid
        assert 'Reviewed skill' in task['brief'] and '<inputs-json>' in task['brief']
        clock[0] += 31
        assert second.detail('founder', config['principals']['founder'], tid)['status'] == 'interrupted'
        assert second.claim('mac-coding-1', config['workers']['mac-coding-1']) is None
        assert second.capabilities.execute('founder', config['principals']['founder'], body(worker_id='mac-coding-1'))['task']['status'] == 'interrupted'
    finally:
        second.close()


def test_normal_task_worker_selection_is_bound_to_idempotency(capabilities):
    c, config, *_ = capabilities
    data = dict(project='snowgloves', brief='Review', idempotency_key='normal', worker_id='wrong-worker')
    task = c.submit('founder', config['principals']['founder'], data)
    assert task['requested_worker'] == 'wrong-worker'
    assert c.claim('mac-coding-1', config['workers']['mac-coding-1']) is None
    assert c.claim('wrong-worker', config['workers']['wrong-worker'])['id'] == task['id']
    with pytest.raises(Rejected):
        c.submit('founder', config['principals']['founder'], dict(data, worker_id='mac-coding-1'))
    with pytest.raises(Rejected):
        c.submit('founder', config['principals']['founder'], dict(data, worker_id='no-such-worker', idempotency_key='other'))


def test_approval_requires_explicit_permission_and_identity_from_auth(capabilities):
    c, config, *_ = capabilities
    approval = request(capabilities)
    assert approval['status'] == 'pending' and approval['inputs'] == {'focus': 'documentation'}
    assert request(capabilities)['id'] == approval['id']
    with pytest.raises(Rejected) as error:
        approve(capabilities, approval['id'], who='founder')
    assert error.value.status == 403
    with pytest.raises(Rejected):
        approve(capabilities, approval['id'], payload={'decided_by': 'founder'})
    assert approve(capabilities, approval['id'])['decided_by'] == 'approver'
    assert approve(capabilities, approval['id'])['status'] == 'approved'
    assert c.capabilities.approvals('outsider', config['principals']['outsider'])['approvals'] == []


def test_approval_bound_to_inputs_project_and_consumed_once(capabilities):
    c, config, *_ = capabilities
    approval = request(capabilities)
    with pytest.raises(Rejected):
        execute(capabilities, capability_id='gated', approval_id=approval['id'])
    approve(capabilities, approval['id'])
    with pytest.raises(Rejected):
        execute(capabilities, capability_id='gated', inputs={'focus': 'changed'}, approval_id=approval['id'])
    result = execute(capabilities, capability_id='gated', approval_id=approval['id'])
    assert execute(capabilities, capability_id='gated', approval_id=approval['id'])['task']['id'] == result['task']['id']
    with pytest.raises(Rejected):
        execute(capabilities, capability_id='gated', idempotency_key='new', approval_id=approval['id'])
    with pytest.raises(Rejected):
        c.capabilities.decide('approver', config['principals']['approver'], approval['id'], 'rejected', {})
    assert c.capabilities.approvals('approver', config['principals']['approver'])['approvals'][0]['status'] == 'consumed'


def test_approval_reject_and_adapter_change_never_dispatch(capabilities):
    c, config, _, root, _ = capabilities
    approval = request(capabilities)
    reject = c.capabilities.decide('approver', config['principals']['approver'], approval['id'], 'rejected', {})
    assert reject['approval']['status'] == 'rejected'
    with pytest.raises(Rejected):
        approve(capabilities, approval['id'])
    other = request(capabilities, idempotency_key='two')
    path = root / 'catalog/execution-registry.json'
    reg = json.loads(path.read_text())
    reg['entries']['gated']['approval_required'] = True
    path.write_text(json.dumps(reg))
    with pytest.raises(Rejected):
        approve(capabilities, other['id'])
    assert c.db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_concurrent_approval_consumption_makes_exactly_one_task(capabilities):
    c, *_ = capabilities
    approval = request(capabilities)
    approve(capabilities, approval['id'])
    results, errors = [], []
    def run(key):
        try:
            results.append(execute(capabilities, capability_id='gated', approval_id=approval['id'], idempotency_key=key))
        except Rejected as error:
            errors.append(error.status)
    threads = [threading.Thread(target=run, args=(key,)) for key in ('a', 'b')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 1 and errors == [409]
    assert c.db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 1


def succeeded_artifact(ctx, **changes):
    c, config, *_ = ctx
    task = execute(ctx)['task']
    assigned = c.claim('mac-coding-1', config['workers']['mac-coding-1'])
    envelope = dict(task_id=task['id'], attempt_id=assigned['attempt_id'], project='snowgloves', runtime='codex', node='coding-01', output='safe founder-secret-token')
    envelope.update(changes)
    artifact = c.artifacts / 'test.json'
    artifact.write_text(json.dumps(envelope))
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    c.report('mac-coding-1', config['workers']['mac-coding-1'], dict(task_id=task['id'], attempt_id=assigned['attempt_id'], lease_token=assigned['lease_token'], event_id='done', type='succeeded', artifact=dict(path=str(artifact), sha256=digest)))
    return task['id'], artifact


def test_artifact_digest_identity_scope_and_current_secret_redaction(capabilities):
    c, config, *_ = capabilities
    tid, path = succeeded_artifact(capabilities)
    result = c.capabilities.artifact('founder', config['principals']['founder'], tid)['artifact']
    assert result['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result['content']['output'] == 'safe [REDACTED]'
    assert 'path' not in result
    with pytest.raises(Rejected) as error:
        c.capabilities.artifact('outsider', config['principals']['outsider'], tid)
    assert error.value.status == 404
    path.write_text('{}')
    with pytest.raises(Rejected):
        c.capabilities.artifact('founder', config['principals']['founder'], tid)


@pytest.mark.parametrize('changes', [{'task_id': 'a' * 32}, {'attempt_id': 'b' * 32}, {'project': 'other'}, {'runtime': 'claude'}, {'node': 'coding-02'}])
def test_artifact_hash_alone_does_not_authorize_another_identity(capabilities, changes):
    c, config, *_ = capabilities
    tid, _ = succeeded_artifact(capabilities, **changes)
    with pytest.raises(Rejected) as error:
        c.capabilities.artifact('founder', config['principals']['founder'], tid)
    assert error.value.status == 409


def test_malformed_activation_is_disabled_and_malformed_schema_is_configuration_error(capabilities):
    c, config, _, root, enabled = capabilities
    registry = root / 'catalog/execution-registry.json'
    value = json.loads(registry.read_text())
    value['entries']['review']['input_schema']['properties']['focus']['type'] = 'array'
    registry.write_text(json.dumps(value))
    assert c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'review')['state'] == 'missing_configuration'
    enabled.write_text('modules: [invalid: {')
    assert c.capabilities.readiness(config['principals']['founder'], 'snowgloves', 'review')['state'] == 'disabled'


def test_cross_tenant_approval_and_capability_visibility_are_independent(capabilities):
    c, config, *_ = capabilities
    config['projects']['other'] = dict(config['projects']['snowgloves'], tenant='other-tenant')
    config['principals']['other'] = {'token': 'other-tenant-token', 'projects': ['other'], 'permissions': ['read', 'submit', 'approve']}
    approval = request(capabilities)
    assert all(row['tenant'] == 'other-tenant' and row['state'] in ('disabled', 'refused')
               for row in c.capabilities.list(config['principals']['other'])['capabilities'])
    assert c.capabilities.approvals('other', config['principals']['other'])['approvals'] == []
    with pytest.raises(Rejected) as error:
        approve(capabilities, approval['id'], who='other')
    assert error.value.status == 404
    with pytest.raises(Rejected):
        c.capabilities.execute('other', config['principals']['other'], body(approval_id=approval['id'], capability_id='gated'))


def test_approval_permission_is_valid_but_never_a_legacy_default(capabilities, tmp_path):
    from lib.fleet_coordinator import load_config
    c, config, *_ = capabilities
    config = json.loads(json.dumps(config))
    repo = Path(config['projects']['snowgloves']['root'])
    (repo / '.git').mkdir(parents=True)
    for group in ('principals', 'workers'):
        for name, entry in config[group].items():
            entry['token'] = name + '-fixture-token-long-enough'
    path = tmp_path / 'coordinator.json'
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    loaded = load_config(path)
    assert loaded['principals']['approver']['permissions'] == ['read', 'approve']
    assert 'permissions' not in loaded['principals']['founder']
    assert 'approve' not in c.capabilities.context(config['principals']['founder'])['permissions']


def test_capability_approval_execution_and_artifact_http_round_trip(capabilities):
    from fleet_mcp import FleetApi, FleetError
    from lib.fleet_coordinator import server
    c, config, *_ = capabilities
    http = server(c, 0)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    endpoint = 'http://127.0.0.1:%d' % http.server_port
    founder = FleetApi(endpoint, config['principals']['founder']['token'])
    approver = FleetApi(endpoint, config['principals']['approver']['token'])
    try:
        approval = founder.request_approval('snowgloves', 'gated', {'focus': 'docs'}, 'http')['approval']
        assert founder.approvals()[0]['id'] == approval['id']
        with pytest.raises(FleetError, match='403'):
            founder.decide_approval(approval['id'], True)
        assert approver.decide_approval(approval['id'], True)['approval']['decided_by'] == 'approver'
        result = founder.execute_capability('snowgloves', 'gated', {'focus': 'docs'}, 'http', approval_id=approval['id'])
        assert founder.status(result['task']['id'])['status'] == 'queued'
        assert founder.execute_capability('snowgloves', 'gated', {'focus': 'docs'}, 'http', approval_id=approval['id'])['task']['id'] == result['task']['id']
        with pytest.raises(FleetError, match='409'):
            founder.artifact(result['task']['id'])
        assert founder.cancel(result['task']['id'])['status'] == 'cancelled'
        assert approver.approvals()[0]['status'] == 'consumed'
    finally:
        http.shutdown()
        http.server_close()

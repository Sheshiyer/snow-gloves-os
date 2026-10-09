"""Bounded Chief-of-Staff fanout stays coordinator-authorized and read-only."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from fleet_hermes_bridge import Bridge
from fleet_worker import Worker
from lib.fleet_coordinator import MAX_FANOUT_BRIEF, Rejected
from test_fleet_coordinator import claim, fleet, report, submit  # noqa: F401  (fleet is a fixture)


def plan(children=None):
    return {'children': children or [
        {'logical_role': 'librarian', 'stage': 'reference', 'title': 'Collect references', 'brief': 'Read the relevant code.'},
        {'logical_role': 'cto', 'stage': 'review', 'title': 'Review implementation', 'brief': 'Review the implementation boundaries.'},
        {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Verify constraints', 'brief': 'Verify the bounded read-only result.'},
    ]}


def enable(conf):
    conf['projects']['snowgloves']['fanout'] = True
    conf['principals']['founder']['fanout_projects'] = ['snowgloves']


def planner(c, result, calls):
    def fake(root):
        calls.append(root)
        return copy.deepcopy(result)
    c._plan_from_hermes = fake


def succeed(c, conf, task, name):
    artifact = c.artifacts / name
    artifact.write_text(json.dumps({
        'task_id': task['id'],
        'attempt_id': task['attempt_id'],
    }))
    return report(c, conf, task, event_id='done-' + task['id'][:12], type='succeeded',
                  artifact={'path': str(artifact), 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()})


def test_fanout_admission_rejects_before_planner_for_config_scope_owner_and_worker(fleet):
    c, conf, _ = fleet
    root = submit(c, conf)
    calls = []
    planner(c, plan(), calls)

    with pytest.raises(Rejected) as exc:
        c.fanout('founder', conf['principals']['founder'], root['id'])
    assert exc.value.status == 403

    conf['projects']['snowgloves']['fanout'] = True
    with pytest.raises(Rejected) as exc:
        c.fanout('founder', conf['principals']['founder'], root['id'])
    assert exc.value.status == 403

    enable(conf)
    conf['principals']['other'] = {
        'token': 'other-owner-secret-token', 'projects': ['snowgloves'], 'fanout_projects': ['snowgloves'],
    }
    with pytest.raises(Rejected) as exc:
        c.fanout('other', conf['principals']['other'], root['id'])
    assert exc.value.status == 404
    with pytest.raises(Rejected) as exc:
        c.authenticate(conf['workers']['mac-coding-1']['token'])
    assert exc.value.status == 401
    assert calls == []


def test_fanout_rejects_nondevelopment_terminal_nested_and_manual_roots_before_planner(fleet):
    c, conf, _ = fleet
    enable(conf)
    calls = []
    planner(c, plan(), calls)

    nondevelopment = submit(c, conf, category='research', idempotency_key='research')
    with pytest.raises(Rejected):
        c.fanout('founder', conf['principals']['founder'], nondevelopment['id'])

    terminal = submit(c, conf, idempotency_key='terminal')
    c.cancel('founder', conf['principals']['founder'], terminal['id'])
    with pytest.raises(Rejected):
        c.fanout('founder', conf['principals']['founder'], terminal['id'])

    parent = submit(c, conf, idempotency_key='parent')
    nested = submit(c, conf, parent_id=parent['id'], logical_role='cto', stage='review',
                    idempotency_key='nested')
    with pytest.raises(Rejected):
        c.fanout('founder', conf['principals']['founder'], nested['id'])
    with pytest.raises(Rejected):
        c.fanout('founder', conf['principals']['founder'], parent['id'])
    assert calls == []


def test_fanout_is_atomic_idempotent_durable_and_audited(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    calls = []
    planner(c, plan(), calls)

    first = c.fanout('founder', conf['principals']['founder'], root['id'])
    again = c.fanout('founder', conf['principals']['founder'], root['id'], {})
    assert again == first and len(calls) == 1
    assert [child['order'] for child in first['children']] == [1, 2, 3]
    assert all(
        (child['parent_id'], child['owner'], child['project'], child['runtime'], child['access'])
        == (root['id'], root['owner'], root['project'], root['runtime'], 'read')
        for child in first['children']
    )
    assert c.db.execute('SELECT count(*) FROM fanout_plans').fetchone()[0] == 1
    events = c.detail('founder', conf['principals']['founder'], root['id'], events=True)
    accepted = [event for event in events if event['type'] == 'chief_of_staff_plan_accepted']
    assert len(accepted) == 1
    audit = json.loads(accepted[0]['message'])
    assert audit['root_id'] == root['id'] and audit['plan_id'] == first['plan_id']
    assert [child['id'] for child in audit['children']] == [child['id'] for child in first['children']]

    c.close()
    reopened = type(c)(conf)
    try:
        reopened._plan_from_hermes = lambda root: pytest.fail('persisted plan must not invoke Hermes')
        restored = reopened.fanout('founder', conf['principals']['founder'], root['id'])
        assert restored['plan_id'] == first['plan_id']
        assert [child['id'] for child in restored['children']] == [child['id'] for child in first['children']]
    finally:
        reopened.close()


def test_coordinator_plan_request_has_only_sanitized_authorized_brief_and_constraints(fleet, monkeypatch):
    c, conf, _ = fleet
    root = submit(c, conf, brief='Review bridge-secret-token without changing scope.')
    enable(conf)
    conf['hermes_bridge'] = {
        'url': 'http://127.0.0.1:4102', 'token': 'bridge-secret-token', 'timeout': 3,
    }
    captured = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, _limit):
            return json.dumps(plan()).encode()

    def fake_open(request, timeout):
        captured['request'], captured['timeout'] = request, timeout
        return Response()

    monkeypatch.setattr('lib.fleet_coordinator.urllib.request.urlopen', fake_open)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])
    body = json.loads(captured['request'].data)
    assert captured['request'].full_url == 'http://127.0.0.1:4102/plan'
    assert captured['request'].get_header('Authorization') == 'Bearer bridge-secret-token'
    assert set(body) == {'brief', 'roles', 'stages'}
    assert 'bridge-secret-token' not in body['brief'] and '[REDACTED]' in body['brief']
    assert body['roles'] == ['ceo', 'cto', 'chief-of-staff', 'librarian', 'interpreter', 'dispatcher', 'sentinel']
    assert result['children'][0]['access'] == 'read'


@pytest.mark.parametrize('bad', [
    lambda: {'children': plan()['children'], 'access': 'write'},
    lambda: plan([{'logical_role': 'librarian', 'stage': 'reference', 'title': 'One', 'brief': 'x' * (MAX_FANOUT_BRIEF + 1)},
                  {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Two', 'brief': 'ok'}]),
    lambda: plan([{'logical_role': 'librarian', 'stage': 'reference', 'title': 'One', 'brief': 'ok', 'access': 'write'},
                  {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Two', 'brief': 'ok'}]),
    lambda: plan([{'logical_role': 'librarian', 'stage': 'reference', 'title': 'One', 'brief': 'ok'},
                  {'logical_role': 'librarian', 'stage': 'review', 'title': 'Two', 'brief': 'ok'},
                  {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Three', 'brief': 'ok'}]),
    lambda: plan([{'logical_role': 'librarian', 'stage': 'reference', 'title': 'One', 'brief': 'ok'},
                  {'logical_role': 'cto', 'stage': 'verify', 'title': 'Two', 'brief': 'ok'}]),
    lambda: plan([{'logical_role': 'sentinel', 'stage': 'verify', 'title': 'One', 'brief': 'ok'},
                  {'logical_role': 'librarian', 'stage': 'reference', 'title': 'Two', 'brief': 'ok'}]),
])
def test_invalid_planner_output_creates_no_plan_or_children(fleet, bad):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    calls = []
    planner(c, bad(), calls)

    with pytest.raises(Rejected) as exc:
        c.fanout('founder', conf['principals']['founder'], root['id'])
    assert exc.value.status == 503 and len(calls) == 1
    assert c.db.execute('SELECT count(*) FROM fanout_plans').fetchone()[0] == 0
    assert c.db.execute('SELECT count(*) FROM tasks WHERE parent_id=?', (root['id'],)).fetchone()[0] == 0


def test_fanout_rechecks_state_after_planning_before_creating_children(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    calls = []

    def cancel_during_plan(_root):
        calls.append(1)
        c.cancel('founder', conf['principals']['founder'], root['id'])
        return plan()

    c._plan_from_hermes = cancel_during_plan
    with pytest.raises(Rejected) as exc:
        c.fanout('founder', conf['principals']['founder'], root['id'])
    assert exc.value.status == 409 and calls == [1]
    assert c.db.execute('SELECT count(*) FROM fanout_plans').fetchone()[0] == 0
    assert c.db.execute('SELECT count(*) FROM tasks WHERE parent_id=?', (root['id'],)).fetchone()[0] == 0


def test_concurrent_fanout_cannot_duplicate_a_durable_plan(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    barrier, calls, results, errors = threading.Barrier(2), [], [], []

    def simultaneous(_root):
        calls.append(1)
        barrier.wait(timeout=3)
        return plan()

    c._plan_from_hermes = simultaneous

    def run():
        try:
            results.append(c.fanout('founder', conf['principals']['founder'], root['id']))
        except BaseException as error:  # preserve thread diagnostics in the assertion
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert not errors and len(results) == 2 and len(calls) == 2
    assert results[0]['plan_id'] == results[1]['plan_id']
    assert [child['id'] for child in results[0]['children']] == [child['id'] for child in results[1]['children']]
    assert c.db.execute('SELECT count(*) FROM fanout_plans').fetchone()[0] == 1
    assert c.db.execute('SELECT count(*) FROM tasks WHERE parent_id=?', (root['id'],)).fetchone()[0] == 3


def test_planned_children_use_one_slot_ordered_prerequisites_and_safe_sources(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    calls = []
    planner(c, plan(), calls)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])

    root_running = claim(c, conf)
    assert root_running['id'] == root['id'] and claim(c, conf) is None
    succeed(c, conf, root_running, 'root.json')
    first = claim(c, conf)
    assert first['id'] == result['children'][0]['id']
    assert first['fanout']['order'] == 1
    assert [source['task_id'] for source in first['source_artifacts']] == [root['id']]
    assert not Path(first['source_artifacts'][0]['artifact']['path']).is_absolute()
    assert claim(c, conf) is None

    succeed(c, conf, first, 'first.json')
    second = claim(c, conf)
    assert second['id'] == result['children'][1]['id']
    assert [source['task_id'] for source in second['source_artifacts']] == [root['id'], first['id']]
    succeed(c, conf, second, 'second.json')
    sentinel = claim(c, conf)
    assert sentinel['id'] == result['children'][2]['id']
    assert sentinel['logical_role'] == 'sentinel' and sentinel['stage'] == 'verify'


def test_failed_planned_predecessor_visibly_blocks_sentinel(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    two = plan([
        {'logical_role': 'cto', 'stage': 'review', 'title': 'Review', 'brief': 'Review boundaries.'},
        {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Verify', 'brief': 'Verify only.'},
    ])
    calls = []
    planner(c, two, calls)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])
    root_running = claim(c, conf)
    succeed(c, conf, root_running, 'root.json')
    predecessor = claim(c, conf)
    report(c, conf, predecessor, event_id='failed-predecessor', type='failed', message='synthetic failure')

    assert claim(c, conf) is None
    sentinel_id = result['children'][-1]['id']
    detail = c.detail('founder', conf['principals']['founder'], sentinel_id)
    assert 'Blocked: planned predecessor' in detail['hold_reason'] and 'failed' in detail['hold_reason']
    graph_rows = {child['id']: child for child in c.detail('founder', conf['principals']['founder'], root['id'])['graph']['children']}
    assert graph_rows[sentinel_id]['hold_reason'] == detail['hold_reason']


def test_fanout_root_rejects_new_manual_child_transactionally(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    calls = []
    planner(c, plan(), calls)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])

    with pytest.raises(Rejected) as exc:
        submit(c, conf, parent_id=root['id'], logical_role='ceo', stage='plan',
               idempotency_key='manual-after-fanout')

    assert exc.value.status == 409
    assert c.db.execute(
        'SELECT count(*) FROM tasks WHERE parent_id=?', (root['id'],)
    ).fetchone()[0] == len(result['children'])


def test_failed_planned_child_retry_retains_slot_and_unblocks_after_success(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    two = plan([
        {'logical_role': 'cto', 'stage': 'review', 'title': 'Review', 'brief': 'Review boundaries.'},
        {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Verify', 'brief': 'Verify only.'},
    ])
    calls = []
    planner(c, two, calls)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])
    root_running = claim(c, conf)
    succeed(c, conf, root_running, 'root.json')
    failed = claim(c, conf)
    report(c, conf, failed, event_id='failed-planned-child', type='failed',
           message='synthetic failure')

    retry = submit(c, conf, parent_id=root['id'], logical_role='cto', stage='review',
                   supersedes=failed['id'], idempotency_key='planned-retry')
    retry_detail = c.detail('founder', conf['principals']['founder'], retry['id'])
    assert retry['supersedes'] == failed['id']
    assert retry_detail['fanout'] == {'plan_id': result['plan_id'], 'order': 1}
    assert c.db.execute(
        'SELECT count(*) FROM fanout_children WHERE plan_id=?', (result['plan_id'],)
    ).fetchone()[0] == 2

    sentinel_id = result['children'][-1]['id']
    waiting = c.detail('founder', conf['principals']['founder'], sentinel_id)
    assert waiting['hold_reason'].startswith('Waiting: planned predecessor')
    running_retry = claim(c, conf)
    assert running_retry['id'] == retry['id']
    assert claim(c, conf) is None
    assert c.detail('founder', conf['principals']['founder'], sentinel_id)['hold_reason'].startswith(
        'Waiting: planned predecessor'
    )

    succeed(c, conf, running_retry, 'retry.json')
    sentinel = claim(c, conf)
    assert sentinel['id'] == sentinel_id
    assert [source['task_id'] for source in sentinel['source_artifacts']] == [
        root['id'], retry['id'],
    ]


@pytest.mark.parametrize('payload', [
    lambda task: b'{}',
    lambda task: b'not-json',
    lambda task: json.dumps({
        'task_id': task['id'],
        'attempt_id': task['attempt_id'] + '-replayed',
    }).encode(),
])
def test_missing_invalid_or_wrong_attempt_source_envelope_holds_planned_child(fleet, payload):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    calls = []
    planner(c, plan(), calls)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])
    root_running = claim(c, conf)
    artifact = c.artifacts / 'unattributed.json'
    artifact.write_bytes(payload(root_running))
    report(c, conf, root_running, type='succeeded', artifact={
        'path': str(artifact),
        'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
    })

    assert claim(c, conf) is None
    detail = c.detail('founder', conf['principals']['founder'], result['children'][0]['id'])
    assert detail['hold_reason'] == 'Blocked: parent artifact integrity check failed'


def test_cross_task_cross_project_artifact_replay_holds_planned_child(fleet):
    c, conf, _ = fleet
    conf['projects']['other'] = {
        'root': conf['projects']['snowgloves']['root'],
        'tenant': 'other-tenant',
        'organization': 'other-organization',
        'runtimes': ['codex'],
    }
    conf['principals']['founder']['projects'].append('other')
    conf['workers']['mac-coding-1']['projects'].append('other')
    foreign = submit(c, conf, project='other', idempotency_key='foreign-project')
    foreign_running = claim(c, conf)
    assert foreign_running['id'] == foreign['id']
    succeed(c, conf, foreign_running, 'foreign.json')

    enable(conf)
    root = submit(c, conf, idempotency_key='fanout-root')
    calls = []
    planner(c, plan(), calls)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])
    root_running = claim(c, conf)
    assert root_running['id'] == root['id']
    replay = c.artifacts / 'foreign.json'
    report(c, conf, root_running, type='succeeded', artifact={
        'path': str(replay),
        'sha256': hashlib.sha256(replay.read_bytes()).hexdigest(),
    })

    assert claim(c, conf) is None
    detail = c.detail('founder', conf['principals']['founder'], result['children'][0]['id'])
    assert detail['hold_reason'] == 'Blocked: parent artifact integrity check failed'


def test_changed_source_artifact_checksum_holds_planned_child(fleet):
    c, conf, _ = fleet
    enable(conf)
    root = submit(c, conf)
    calls = []
    planner(c, plan(), calls)
    result = c.fanout('founder', conf['principals']['founder'], root['id'])
    root_running = claim(c, conf)
    succeed(c, conf, root_running, 'root.json')
    (c.artifacts / 'root.json').write_text('changed after coordinator report')

    assert claim(c, conf) is None
    detail = c.detail('founder', conf['principals']['founder'], result['children'][0]['id'])
    assert detail['hold_reason'] == 'Blocked: parent artifact integrity check failed'


def test_manual_graph_and_native_task_claim_remain_unplanned(fleet):
    c, conf, _ = fleet
    root = submit(c, conf)
    root_running = claim(c, conf)
    assert 'fanout' not in root_running and 'source_artifacts' not in root_running
    succeed(c, conf, root_running, 'root.json')
    manual = submit(c, conf, parent_id=root['id'], logical_role='sentinel', stage='verify',
                    idempotency_key='manual')
    child = claim(c, conf)
    assert child['id'] == manual['id']
    assert 'fanout' not in child and 'source_artifacts' not in child
    assert 'hold_reason' not in c.detail('founder', conf['principals']['founder'], manual['id'])


def test_bridge_plan_uses_no_tools_and_rejects_model_authority_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', lambda *args, **kwargs: 'revision\n')
    key = tmp_path / 'gateway.key'
    key.write_text('gateway-secret')
    key.chmod(0o600)
    bridge = Bridge({
        'token': 'bridge-secret', 'hermes_root': '/hermes', 'hermes_revision': 'revision',
        'hermes_python': '/python', 'hermes_profile': 'snowgloves', 'gateway_key_file': str(key),
        'gateway_url': 'http://127.0.0.1:20128/v1',
    })
    commands = []

    def fake(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'type': 'result', 'exit_code': 0, 'text': json.dumps(plan()),
        }) + '\n', '')

    monkeypatch.setattr(subprocess, 'run', fake)
    body = {'brief': 'Review this authorized root.', 'roles': ['ceo', 'cto', 'chief-of-staff', 'librarian', 'interpreter', 'dispatcher', 'sentinel'],
            'stages': ['plan', 'reference', 'review', 'dispatch', 'verify']}
    assert bridge.plan(body) == plan()
    command, kwargs = commands[-1]
    assert '--safe-mode' in command and 'snowgloves-none' in command
    assert 'Chief-of-Staff planner' in kwargs['env']['HERMES_EPHEMERAL_SYSTEM_PROMPT']
    assert json.loads(kwargs['input'].splitlines()[-1]) == body

    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, json.dumps({'type': 'result', 'exit_code': 0, 'text': json.dumps({
            'children': [
                {'logical_role': 'librarian', 'stage': 'reference', 'title': 'One', 'brief': 'one', 'access': 'write'},
                {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Two', 'brief': 'two'},
            ],
        })}) + '\n', ''))
    with pytest.raises(ValueError):
        bridge.plan(body)


def test_planned_worker_prompt_and_artifact_keep_validated_role_and_safe_metadata(fleet, tmp_path):
    c, conf, _ = fleet
    enable(conf)
    root_path = Path(conf['projects']['snowgloves']['root'])
    root_path.mkdir()
    subprocess.run(['git', 'init', str(root_path)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root_path), '-c', 'user.name=Test', '-c',
                    'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'initial'],
                   check=True, capture_output=True)
    root = submit(c, conf)
    calls = []
    planner(c, plan([
        {'logical_role': 'librarian', 'stage': 'reference', 'title': 'References', 'brief': 'Never use gateway-secret.'},
        {'logical_role': 'sentinel', 'stage': 'verify', 'title': 'Verify', 'brief': 'Verify result.'},
    ]), calls)
    c.fanout('founder', conf['principals']['founder'], root['id'])
    root_running = claim(c, conf)
    succeed(c, conf, root_running, 'root.json')
    assigned = claim(c, conf)

    key, prompt_path, cli = tmp_path / 'key', tmp_path / 'prompt.txt', tmp_path / 'codex'
    key.write_text('gateway-secret')
    key.chmod(0o600)
    cli.write_text(
        '#!/usr/bin/env python3\n'
        'import json, sys\n'
        'from pathlib import Path\n'
        'Path(%r).write_text(sys.stdin.read())\n'
        'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"done gateway-secret"}}))\n'
        % str(prompt_path)
    )
    cli.chmod(0o700)
    worker = Worker({
        'endpoint': 'http://127.0.0.1:4101', 'token': 'worker-secret-token', 'node_id': 'test-node',
        'gateway_url': 'http://127.0.0.1:20128/v1', 'gateway_key_file': str(key),
        'state_root': str(tmp_path / 'worker-state'), 'codex_path': str(cli),
        'allowed_roots': [str(root_path)], 'artifacts_root': str(c.artifacts),
    })
    reports = []
    worker.request = lambda route, body: reports.append(body) or {}
    worker.execute(assigned)
    assert reports[-1]['type'] == 'succeeded'
    prompt = prompt_path.read_text()
    assert 'AUTHORITATIVE ASSIGNMENT' in prompt and '"logical_role": "librarian"' in prompt
    assert 'BEGIN UNTRUSTED BRIEF' in prompt and 'gateway-secret' not in prompt
    artifact = json.loads(Path(reports[-1]['artifact']['path']).read_text())
    assert artifact['logical_role'] == 'librarian'
    assert artifact['stage'] == 'reference' and artifact['parent_id'] == root['id']
    assert artifact['source_artifacts'] == assigned['source_artifacts']

    bad = copy.deepcopy(assigned)
    bad['source_artifacts'][0]['artifact']['path'] = '/etc/passwd'
    bad_worker = Worker({**worker.config, 'state_root': str(tmp_path / 'bad-worker-state')})
    bad_reports = []
    bad_worker.request = lambda route, body: bad_reports.append(body) or {}
    bad_worker.execute(bad)
    assert bad_reports[-1]['type'] == 'failed'
    assert not (bad_worker.state / 'worktrees').exists()


def test_fleet_tasks_cli_posts_empty_fanout_body(monkeypatch):
    import fleet_tasks

    captured = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, *args):
            return b'{"plan_id":"p","root_id":"r","children":[]}'

    def fake_open(request, timeout):
        captured['request'], captured['timeout'] = request, timeout
        return Response()

    monkeypatch.setattr(fleet_tasks.urllib.request, 'urlopen', fake_open)
    monkeypatch.setenv('SNOWGLOVES_FLEET_TOKEN', 'founder-secret-token')
    monkeypatch.setattr(sys, 'argv', ['fleet_tasks.py', '--endpoint', 'http://127.0.0.1:4101',
                                      'fanout', 'a' * 32])
    assert fleet_tasks.main() == 0
    assert captured['request'].full_url.endswith('/v1/tasks/' + 'a' * 32 + '/fanout')
    assert captured['request'].data == b'{}' and captured['timeout'] == 100

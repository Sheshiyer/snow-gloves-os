"""Remote worker artifacts stay authenticated, bounded, and coordinator-owned."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_worker import Worker
from lib.fleet_coordinator import (
    MAX_HTTP_BODY_BYTES,
    MAX_REMOTE_ARTIFACT_BYTES,
    Coordinator,
    Rejected,
    _bounded_json_object,
    load_config,
)


FOUNDER_TOKEN = 'founder-credential-token-0001'
REMOTE_TOKEN = 'remote-worker-credential-0001'
OTHER_TOKEN = 'other-worker-credential-0002'


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def artifact(task, node='coding02', **updates):
    envelope = {
        'task_id': task['id'],
        'attempt_id': task['attempt_id'],
        'project': task['project'],
        'node': node,
        'runtime': task['runtime'],
        'model': 'noesis-fast',
        'output': 'remote result',
    }
    envelope.update(updates)
    content = compact(envelope)
    return {'content': content.decode('utf-8'), 'sha256': hashlib.sha256(content).hexdigest()}


def submit(coordinator, config, key='remote-task'):
    return coordinator.submit('founder', config['principals']['founder'], {
        'project': 'snowgloves',
        'brief': 'Review the remote worktree',
        'runtime': 'codex',
        'idempotency_key': key,
    })


def report(coordinator, config, task, body, name='coding02'):
    payload = {
        'task_id': task['id'],
        'attempt_id': task['attempt_id'],
        'lease_token': task['lease_token'],
        'event_id': 'remote-event',
        'type': 'succeeded',
        'artifact': artifact(task),
    }
    payload.update(body)
    return coordinator.report(name, config['workers'][name], payload)


@pytest.fixture
def remote_fleet(tmp_path):
    config = {
        'data_root': str(tmp_path / 'ops'),
        'projects': {
            # This intentionally does not name a usable coordinator worktree.
            # A remote claim must neither expose nor resolve it.
            'snowgloves': {
                'root': '/coordinator/does-not-share-this-worktree',
                'tenant': 'heyzack',
                'organization': 'heyzack',
                'runtimes': ['codex'],
            },
        },
        'principals': {
            'founder': {'token': FOUNDER_TOKEN, 'projects': ['snowgloves']},
        },
        'workers': {
            'coding02': {
                'token': REMOTE_TOKEN,
                'projects': ['snowgloves'],
                'runtimes': ['codex'],
                'remote_artifacts': True,
                'node_id': 'coding02',
            },
            'other-remote': {
                'token': OTHER_TOKEN,
                'projects': ['snowgloves'],
                'runtimes': ['codex'],
                'remote_artifacts': True,
                'node_id': 'other-remote',
            },
        },
        'capacity': 1,
        'lease_seconds': 30,
    }
    now = [100.0]
    coordinator = Coordinator(config, clock=lambda: now[0])
    yield coordinator, config, now
    coordinator.close()


def test_remote_success_uses_local_mapping_and_coordinator_artifact(tmp_path, remote_fleet):
    coordinator, config, _ = remote_fleet
    root = tmp_path / 'remote-checkout'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run([
        'git', '-C', str(root), '-c', 'user.name=Remote Test',
        '-c', 'user.email=remote@example.invalid', 'commit', '--allow-empty',
        '-q', '-m', 'initial',
    ], check=True)
    gateway_key = tmp_path / 'gateway.key'
    gateway_key.write_text('gateway-secret')
    gateway_key.chmod(0o600)
    cli = tmp_path / 'fake-codex'
    cli.write_text(
        '#!/usr/bin/env python3\n'
        'import json, sys\n'
        'sys.stdin.read()\n'
        'print(json.dumps({"type":"item.completed","item":{"type":"agent_message",'
        '"text":"done gateway-secret founder-credential-token-0001"}}))\n'
    )
    cli.chmod(0o700)
    worker = Worker({
        'endpoint': 'http://127.0.0.1:4101',
        'token': REMOTE_TOKEN,
        'node_id': 'coding02',
        'state_root': str(tmp_path / 'worker-state'),
        'allowed_roots': [str(root)],
        'project_roots': {'snowgloves': str(root)},
        'remote_artifacts': True,
        'gateway_url': 'http://127.0.0.1:20128/v1',
        'gateway_key_file': str(gateway_key),
        'codex_path': str(cli),
    })
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    assert task['remote_artifacts'] is True
    assert 'root' not in task and 'artifacts_root' not in task
    # A forwarded assignment cannot make the remote worker use coordinator paths.
    task['root'] = '/coordinator/attempted-path-escape'
    task['artifacts_root'] = '/coordinator/attempted-artifact-escape'
    reports = []

    def request(route, body):
        assert route == '/v1/worker/report'
        reports.append(body)
        return coordinator.report('coding02', config['workers']['coding02'], body)

    worker.request = request
    worker.execute(task)
    terminal = reports[-1]
    assert terminal['type'] == 'succeeded'
    assert set(terminal['artifact']) == {'content', 'sha256'}
    assert len(terminal['artifact']['content'].encode('utf-8')) <= MAX_REMOTE_ARTIFACT_BYTES
    detail = coordinator.detail('founder', config['principals']['founder'], task['id'])
    stored = coordinator.artifacts / detail['artifact']['path']
    assert stored.name.startswith('remote-%s-%s-' % (task['id'], task['attempt_id']))
    saved = json.loads(stored.read_text())
    assert {key: saved[key] for key in ('task_id', 'attempt_id', 'project', 'node')} == {
        'task_id': task['id'],
        'attempt_id': task['attempt_id'],
        'project': 'snowgloves',
        'node': 'coding02',
    }
    assert 'gateway-secret' not in stored.read_text()
    assert FOUNDER_TOKEN not in stored.read_text()
    assert '[REDACTED]' in stored.read_text()


def test_remote_claim_preserves_single_global_active_job(remote_fleet):
    coordinator, config, _ = remote_fleet
    submit(coordinator, config, 'first')
    submit(coordinator, config, 'second')
    assert coordinator.claim('coding02', config['workers']['coding02'])
    assert coordinator.claim('other-remote', config['workers']['other-remote']) is None


def test_remote_report_rejects_forged_cross_worker_before_writing(remote_fleet):
    coordinator, config, _ = remote_fleet
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    with pytest.raises(Rejected) as exc:
        report(coordinator, config, task, {}, name='other-remote')
    assert exc.value.status == 403
    assert not list(coordinator.artifacts.iterdir())


def test_remote_report_rejects_stale_lease_before_writing(remote_fleet):
    coordinator, config, now = remote_fleet
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    now[0] += 31
    with pytest.raises(Rejected) as exc:
        report(coordinator, config, task, {})
    assert exc.value.status == 409
    assert not list(coordinator.artifacts.iterdir())


def test_remote_report_rejects_bad_digest_and_envelope_before_writing(remote_fleet):
    coordinator, config, _ = remote_fleet
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    wrong_digest = artifact(task)
    wrong_digest['sha256'] = '0' * 64
    with pytest.raises(Rejected) as exc:
        report(coordinator, config, task, {'artifact': wrong_digest})
    assert exc.value.status == 400
    wrong_envelope = artifact(task, node='other-remote')
    with pytest.raises(Rejected) as exc:
        report(coordinator, config, task, {'artifact': wrong_envelope, 'event_id': 'wrong-envelope'})
    assert exc.value.status == 400
    assert not list(coordinator.artifacts.iterdir())


def test_remote_report_rejects_oversized_content_before_writing(remote_fleet):
    coordinator, config, _ = remote_fleet
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    content = 'x' * (MAX_REMOTE_ARTIFACT_BYTES + 1)
    oversized = {'content': content, 'sha256': hashlib.sha256(content.encode()).hexdigest()}
    with pytest.raises(Rejected) as exc:
        report(coordinator, config, task, {'artifact': oversized})
    assert exc.value.status == 413
    assert not list(coordinator.artifacts.iterdir())


def test_remote_report_duplicate_is_idempotent_before_file_write(remote_fleet):
    coordinator, config, _ = remote_fleet
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    first = report(coordinator, config, task, {'event_id': 'same-event'})
    files = list(coordinator.artifacts.iterdir())
    assert first == {'accepted': True, 'duplicate': False, 'cancel_requested': False}
    assert len(files) == 1
    before = files[0].read_bytes()
    duplicate = report(coordinator, config, task, {'event_id': 'same-event'})
    assert duplicate == {'accepted': True, 'duplicate': True, 'cancel_requested': False}
    assert list(coordinator.artifacts.iterdir()) == files
    assert files[0].read_bytes() == before


def test_remote_worker_rejects_project_mapping_outside_allowlist(tmp_path):
    root, outside = tmp_path / 'allowed', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    config = {
        'endpoint': 'http://127.0.0.1:4101',
        'token': REMOTE_TOKEN,
        'node_id': 'coding02',
        'state_root': str(tmp_path / 'state'),
        'allowed_roots': [str(root)],
        'project_roots': {'snowgloves': str(outside)},
        'remote_artifacts': True,
        'gateway_url': 'http://127.0.0.1:20128/v1',
    }
    with pytest.raises(ValueError, match='outside allowed_roots'):
        Worker(config)


def test_remote_only_coordinator_config_has_no_filesystem_root_dependency(tmp_path):
    config = {
        'data_root': str(tmp_path / 'ops'),
        'projects': {'snowgloves': {'tenant': 't', 'organization': 'o', 'runtimes': ['codex']}},
        'principals': {'founder': {'token': FOUNDER_TOKEN, 'projects': ['snowgloves']}},
        'workers': {
            'coding02': {
                'token': REMOTE_TOKEN,
                'projects': ['snowgloves'],
                'runtimes': ['codex'],
                'remote_artifacts': True,
                'node_id': 'coding02',
            },
        },
    }
    path = tmp_path / 'coordinator.json'
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    assert load_config(path)['projects']['snowgloves'].get('root') is None


def test_legacy_local_worker_still_reports_a_coordinator_file(tmp_path):
    root = tmp_path / 'local-checkout'
    (root / '.git').mkdir(parents=True)
    config = {
        'data_root': str(tmp_path / 'ops'),
        'projects': {
            'snowgloves': {
                'root': str(root),
                'tenant': 't',
                'organization': 'o',
                'runtimes': ['codex'],
            },
        },
        'principals': {'founder': {'token': FOUNDER_TOKEN, 'projects': ['snowgloves']}},
        'workers': {
            'local': {'token': REMOTE_TOKEN, 'projects': ['snowgloves'], 'runtimes': ['codex']},
        },
    }
    coordinator = Coordinator(config)
    try:
        task = coordinator.submit('founder', config['principals']['founder'], {
            'project': 'snowgloves',
            'brief': 'Local task',
            'runtime': 'codex',
            'idempotency_key': 'local',
        })
        task = coordinator.claim('local', config['workers']['local'])
        assert task['root'] == str(root.resolve())
        assert task['artifacts_root'] == str(coordinator.artifacts)
        local = coordinator.artifacts / 'legacy.json'
        local.write_text('{"local":true}')
        result = coordinator.report('local', config['workers']['local'], {
            'task_id': task['id'],
            'attempt_id': task['attempt_id'],
            'lease_token': task['lease_token'],
            'event_id': 'legacy-success',
            'type': 'succeeded',
            'artifact': {
                'path': str(local),
                'sha256': hashlib.sha256(local.read_bytes()).hexdigest(),
            },
        })
        assert result['accepted']
    finally:
        coordinator.close()


def test_http_body_decoder_rejects_oversized_payload_before_json_parsing():
    with pytest.raises(Rejected) as exc:
        _bounded_json_object(b'{' + b'x' * MAX_HTTP_BODY_BYTES, MAX_HTTP_BODY_BYTES)
    assert exc.value.status == 413


def test_remote_artifact_redacts_current_lease_and_nested_credentials(remote_fleet):
    coordinator, config, _ = remote_fleet
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    supplied = artifact(task, output=task['lease_token'], extra={task['lease_token']: [FOUNDER_TOKEN, REMOTE_TOKEN]})
    report(coordinator, config, task, {'artifact': supplied})
    saved = next(coordinator.artifacts.iterdir()).read_text()
    assert all(secret not in saved for secret in (task['lease_token'], FOUNDER_TOKEN, REMOTE_TOKEN))
    assert json.loads(saved)['output'] == '[REDACTED]'


@pytest.mark.parametrize('field', ['task_id', 'attempt_id', 'project', 'runtime'])
def test_remote_envelope_cannot_change_assignment_context(remote_fleet, field):
    coordinator, config, _ = remote_fleet
    submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    with pytest.raises(Rejected) as exc:
        report(coordinator, config, task, {'artifact': artifact(task, **{field: 'forged'})})
    assert exc.value.status == 400
    assert not list(coordinator.artifacts.iterdir())


@pytest.mark.parametrize('modes,expected', [(None, 'read'), (['read'], 'read'), (['write'], 'write'), (['read', 'write'], 'write')])
def test_remote_worker_claim_respects_access_capability(remote_fleet, modes, expected):
    coordinator, config, _ = remote_fleet
    config['projects']['snowgloves']['write'] = True
    principal = config['principals']['founder']
    principal['write_projects'] = ['snowgloves']
    parent = submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    report(coordinator, config, task, {})
    coordinator.submit('founder', principal, {
        'project': 'snowgloves', 'brief': 'bounded write', 'runtime': 'codex',
        'idempotency_key': 'writer', 'parent_id': parent['id'], 'logical_role': 'cto',
        'stage': 'review', 'access': 'write',
    })
    submit(coordinator, config, key='read-next')
    if modes is not None:
        config['workers']['coding02']['access_modes'] = modes
    task = coordinator.claim('coding02', config['workers']['coding02'])
    assert task['access'] == expected


def test_remote_cancellation_rejects_artifact_before_file_write(remote_fleet):
    coordinator, config, _ = remote_fleet
    submitted = submit(coordinator, config)
    task = coordinator.claim('coding02', config['workers']['coding02'])
    coordinator.cancel('founder', config['principals']['founder'], submitted['id'])
    with pytest.raises(Rejected) as exc:
        report(coordinator, config, task, {})
    assert exc.value.status == 409
    assert not list(coordinator.artifacts.iterdir())

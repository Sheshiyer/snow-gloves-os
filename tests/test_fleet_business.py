"""Commercial preparation stays source-tested, read-only, and connector-free."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


@pytest.mark.parametrize('role', ['buyer', 'sales-follow-up', 'finance-admin'])
def test_non_estimator_price_preparation_needs_catalog(business_fleet, role):
    coordinator, config, _ = business_fleet
    business = config['projects']['synthetic-project']['business']
    business['domain_roles'].append(role)
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, business_context=context(role))
    assert error.value.status == 409
    business['readiness']['reconciliation_status'] = 'verified'
    task = submit(coordinator, config, business_context=context(role))
    assert task['access'] == 'read'


@pytest.mark.parametrize('field', ['record_id', 'source_revision', 'evidence_ref'])
def test_opaque_credentials_reject_before_storage(business_fleet, field):
    coordinator, config, _ = business_fleet
    credential = 'a9' * 32
    config['principals']['founder']['token'] = credential
    supplied = context()
    if field == 'evidence_ref':
        config['projects']['synthetic-project']['business']['readiness'][field] = credential
    else:
        supplied[field] = credential
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, business_context=supplied)
    assert error.value.status == 400
    assert credential not in error.value.message
    assert coordinator.list_tasks('founder', config['principals']['founder']) == []


def test_changed_snapshot_has_visible_hold_and_does_not_starve_intake(business_fleet):
    coordinator, config, _ = business_fleet
    business = config['projects']['synthetic-project']['business']
    business['readiness']['reconciliation_status'] = 'verified'
    estimator = submit(coordinator, config, key='estimator', business_context=context('estimator'))
    business['readiness']['revision'] = 'catalog-synthetic-r2'
    intake = submit(coordinator, config, key='intake', business_context=context())
    detail = coordinator.detail('founder', config['principals']['founder'], estimator['id'])
    assert detail['status'] == 'queued'
    assert detail['business_gate']['dispatch_ready'] is False
    assert 'Catalog readiness' in detail['business_gate']['reason']
    claimed = coordinator.claim('worker-1', config['workers']['worker-1'])
    assert claimed['id'] == intake['id']


def test_cli_business_child_inherits_without_context_file(business_fleet, monkeypatch):
    coordinator, config, _ = business_fleet
    parent = submit(coordinator, config, business_context=context())
    monkeypatch.setenv('SNOWGLOVES_FLEET_TOKEN', config['principals']['founder']['token'])

    class Response(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *unused):
            self.close()

    def dispatch(request, timeout):
        body = json.loads(request.data)
        task = coordinator.submit('founder', config['principals']['founder'], body)
        assert task['business_context'] == parent['business_context']
        return Response(json.dumps(task).encode())

    monkeypatch.setattr(fleet_tasks.urllib.request, 'urlopen', dispatch)
    monkeypatch.setattr(sys, 'argv', ['fleet_tasks.py', 'submit', '--project', 'synthetic-project',
                        '--brief', 'Verify the intake draft', '--parent', parent['id'],
                        '--role', 'sentinel', '--stage', 'verify'])
    assert fleet_tasks.main() == 0


def test_catalog_cannot_be_added_to_an_existing_intake_graph(business_fleet):
    coordinator, config, _ = business_fleet
    supplied = context()
    supplied.pop('catalog_revision')
    parent = submit(coordinator, config, business_context=supplied)
    config['projects']['synthetic-project']['business']['readiness']['reconciliation_status'] = 'verified'
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='new-catalog-child', parent_id=parent['id'],
               logical_role='chief-of-staff', stage='plan', business_context=context('estimator'))
    assert error.value.status == 409

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import fleet_tasks
from fleet_hermes_bridge import Bridge
from fleet_worker import Worker
from lib import fleet_coordinator as coordinator_module
from lib.fleet_business import (
    BUSINESS_CONTEXT_SCHEMA,
    COMMERCIAL_PREPARATION_CATEGORY,
    load_business_roles,
    template_for,
)
from lib.fleet_coordinator import Coordinator, Rejected


def context(domain_role='commercial-secretary', **changes):
    value = {
        'schema': BUSINESS_CONTEXT_SCHEMA,
        'domain_role': domain_role,
        'instance_ref': 'erp-synthetic-01',
        'record_type': 'opportunity',
        'record_id': 'record-synthetic-01',
        'dossier_id': 'dossier-synthetic-01',
        'source_revision': 'source-synthetic-r1',
        'catalog_revision': 'catalog-synthetic-r1',
    }
    value.update(changes)
    return value


def project(root):
    return {
        'root': str(root),
        'tenant': 'synthetic-tenant',
        'organization': 'synthetic-organization',
        'runtimes': ['codex'],
        'business': {
            'instance_refs': ['erp-synthetic-01'],
            'record_types': ['opportunity', 'dossier'],
            'domain_roles': [
                'commercial-secretary',
                'cctp-analyst',
                'marketing-director',
                'content-creator',
                'estimator',
            ],
            'readiness': {
                'revision': 'catalog-synthetic-r1',
                'reconciliation_status': 'pending',
                'evidence_ref': 'catalog-evidence-synthetic-r1',
            },
        },
    }


@pytest.fixture
def business_fleet(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    config = {
        'data_root': str(tmp_path / 'ops'),
        'projects': {'synthetic-project': project(root)},
        'principals': {
            'founder': {
                'token': 'founder-synthetic-token',
                'projects': ['synthetic-project'],
            },
        },
        'workers': {
            'worker-1': {
                'token': 'worker-synthetic-token',
                'projects': ['synthetic-project'],
                'runtimes': ['codex'],
            },
        },
        'capacity': 1,
    }
    now = [100.0]
    coordinator = Coordinator(config, clock=lambda: now[0])
    yield coordinator, config, now
    coordinator.close()


def submit(coordinator, config, key='business-task', **changes):
    body = {
        'project': 'synthetic-project',
        'brief': 'Prepare a source-linked draft only',
        'runtime': 'codex',
        'idempotency_key': key,
    }
    body.update(changes)
    return coordinator.submit('founder', config['principals']['founder'], body)


def report(coordinator, config, task, event_type, **changes):
    body = {
        'task_id': task['id'],
        'attempt_id': task['attempt_id'],
        'lease_token': task['lease_token'],
        'event_id': 'event-' + task['attempt_id'],
        'type': event_type,
    }
    body.update(changes)
    return coordinator.report('worker-1', config['workers']['worker-1'], body)


def finish(coordinator, config, task_id):
    task = coordinator.claim('worker-1', config['workers']['worker-1'])
    assert task and task['id'] == task_id
    artifact = coordinator.artifacts / (task_id + '.json')
    artifact.write_text('{"prepared": true}')
    return report(
        coordinator,
        config,
        task,
        'succeeded',
        artifact={
            'path': str(artifact),
            'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
        },
    )


def test_public_role_registry_has_only_reusable_preparation_templates():
    roles = load_business_roles()
    assert len(roles) == 19
    assert {role['id'] for role in roles if role['price_dependent']} == {'estimator', 'buyer', 'sales-follow-up', 'finance-admin'}
    assert all(role['preparation_only'] is True for role in roles)
    assert all(
        set(role) == {
            'id', 'name', 'desk', 'control_owner', 'mission', 'deliverables',
            'preparation_only', 'price_dependent',
        }
        for role in roles
    )
    assert template_for('commercial-secretary')['control_owner'] == 'interpreter'


def test_development_submission_stays_unchanged_without_business_context(business_fleet):
    coordinator, config, _ = business_fleet
    task = submit(coordinator, config, key='development-task')
    assert task['category'] == 'development'
    assert 'business_context' not in task
    assert task['access'] == 'read'
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='top-level-domain-role', domain_role='commercial-secretary')
    assert error.value.status == 400


def test_existing_database_gets_nullable_business_context_migration(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    data_root = tmp_path / 'ops'
    data_root.mkdir()
    db = sqlite3.connect(data_root / 'fleet.sqlite3')
    db.executescript('''
        CREATE TABLE tasks (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, project TEXT NOT NULL,
          title TEXT NOT NULL, brief TEXT NOT NULL, runtime TEXT NOT NULL,
          category TEXT NOT NULL, idem TEXT NOT NULL, request_hash TEXT NOT NULL,
          status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
          worker TEXT, attempt_id TEXT, lease_hash TEXT, deadline REAL,
          artifact TEXT, logical_role TEXT NOT NULL DEFAULT 'cto',
          UNIQUE(owner, idem));
        CREATE TABLE events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
          attempt_id TEXT NOT NULL, event_id TEXT NOT NULL, type TEXT NOT NULL,
          message TEXT NOT NULL, created REAL NOT NULL,
          UNIQUE(task_id, attempt_id, event_id));
        INSERT INTO tasks(
          id, owner, project, title, brief, runtime, category, idem,
          request_hash, status, created, updated
        ) VALUES (
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'founder', 'synthetic-project',
          'Legacy', 'Legacy task', 'codex', 'development', 'legacy',
          'digest', 'queued', 1, 1
        );
    ''')
    db.commit()
    db.close()
    config = {
        'data_root': str(data_root),
        'projects': {'synthetic-project': project(root)},
        'principals': {'founder': {'token': 'founder-synthetic-token', 'projects': ['synthetic-project']}},
        'workers': {},
    }
    coordinator = Coordinator(config)
    try:
        columns = {row[1] for row in coordinator.db.execute('PRAGMA table_info(tasks)')}
        legacy = coordinator.detail('founder', config['principals']['founder'], 'a' * 32)
        assert 'business_context' in columns
        assert 'business_context' not in legacy
    finally:
        coordinator.close()


@pytest.mark.parametrize('bad_context', [
    {'schema': BUSINESS_CONTEXT_SCHEMA},
    context(instance_ref='https://erp.example.invalid/record'),
    context(record_id='r' * 129),
    context(reconciliation_status=True),
])
def test_malformed_or_oversized_context_is_rejected(business_fleet, bad_context):
    coordinator, config, _ = business_fleet
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='bad-' + str(len(str(bad_context))), business_context=bad_context)
    assert error.value.status == 400


def test_unadmitted_instance_and_wrong_project_context_are_rejected(business_fleet):
    coordinator, config, _ = business_fleet
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='wrong-instance', business_context=context(instance_ref='erp-synthetic-02'))
    assert error.value.status == 403

    other = project(Path(config['projects']['synthetic-project']['root']))
    other['business']['instance_refs'] = ['erp-synthetic-02']
    config['projects']['other-synthetic-project'] = other
    config['principals']['founder']['projects'].append('other-synthetic-project')
    with pytest.raises(Rejected) as error:
        submit(
            coordinator,
            config,
            key='wrong-project',
            project='other-synthetic-project',
            business_context=context(),
        )
    assert error.value.status == 403


def test_unknown_template_missing_config_and_dedupe_conflict_skip_hermes(business_fleet, monkeypatch):
    coordinator, config, _ = business_fleet
    calls = []
    config['hermes_bridge'] = {
        'url': 'http://127.0.0.1:4102',
        'token': 'bridge-synthetic-token',
        'timeout': 1,
    }
    monkeypatch.setattr(
        coordinator_module.urllib.request,
        'urlopen',
        lambda *args, **kwargs: calls.append((args, kwargs)) or (_ for _ in ()).throw(AssertionError('Hermes called')),
    )
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='unknown-template', business_context=context('not-a-template'))
    assert error.value.status == 400

    config['projects']['synthetic-project'].pop('business')
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='missing-config', business_context=context())
    assert error.value.status == 403
    assert calls == []

    config['projects']['synthetic-project']['business'] = project(
        Path(config['projects']['synthetic-project']['root'])
    )['business']
    config.pop('hermes_bridge')
    first = submit(coordinator, config, key='same-context', business_context=context())
    config['hermes_bridge'] = {
        'url': 'http://127.0.0.1:4102',
        'token': 'bridge-synthetic-token',
        'timeout': 1,
    }
    with pytest.raises(Rejected) as error:
        submit(
            coordinator,
            config,
            key='same-context',
            business_context=context(record_id='record-synthetic-02'),
        )
    assert error.value.status == 409
    assert first['id'] and calls == []


def test_normalized_context_is_idempotent_and_changed_reference_conflicts(business_fleet):
    coordinator, config, _ = business_fleet
    original = context()
    reversed_order = dict(reversed(list(original.items())))
    first = submit(coordinator, config, key='normalized', business_context=original)
    replay = submit(coordinator, config, key='normalized', business_context=reversed_order)
    assert replay['id'] == first['id']
    with pytest.raises(Rejected) as error:
        submit(
            coordinator,
            config,
            key='normalized',
            business_context=context(record_id='record-synthetic-02'),
        )
    assert error.value.status == 409


def test_children_inherit_immutable_scope_and_retries_preserve_template(business_fleet):
    coordinator, config, _ = business_fleet
    config['projects']['synthetic-project']['business']['readiness']['reconciliation_status'] = 'verified'
    parent = submit(coordinator, config, key='parent', business_context=context())
    inherited = submit(
        coordinator,
        config,
        key='inherited',
        parent_id=parent['id'],
        logical_role='dispatcher',
        stage='review',
    )
    assert inherited['business_context'] == parent['business_context']
    assert inherited['logical_role'] == 'dispatcher'

    estimator = submit(
        coordinator,
        config,
        key='estimator-child',
        parent_id=parent['id'],
        logical_role='dispatcher',
        stage='review',
        business_context=context('estimator'),
    )
    assert estimator['business_context']['domain_role'] == 'estimator'
    assert estimator['logical_role'] == 'dispatcher'  # domain role never grants a control role

    with pytest.raises(Rejected) as error:
        submit(
            coordinator,
            config,
            key='changed-dossier',
            parent_id=parent['id'],
            logical_role='dispatcher',
            stage='review',
            business_context=context(dossier_id='dossier-synthetic-02'),
        )
    assert error.value.status == 409

    finish(coordinator, config, parent['id'])
    running = coordinator.claim('worker-1', config['workers']['worker-1'])
    assert running['id'] == inherited['id']
    report(coordinator, config, running, 'failed')
    with pytest.raises(Rejected) as error:
        submit(
            coordinator,
            config,
            key='changed-retry-template',
            parent_id=parent['id'],
            logical_role='dispatcher',
            stage='review',
            supersedes=inherited['id'],
            business_context=context('estimator'),
        )
    assert error.value.status == 409
    retry = submit(
        coordinator,
        config,
        key='same-retry-template',
        parent_id=parent['id'],
        logical_role='dispatcher',
        stage='review',
        supersedes=inherited['id'],
    )
    assert retry['business_context'] == inherited['business_context']
    graph = coordinator.detail('founder', config['principals']['founder'], parent['id'])['graph']
    assert graph['business_context'] == parent['business_context']
    assert graph['children'][0]['business_context'] == parent['business_context']


def test_pending_catalog_allows_secretary_but_not_estimator(business_fleet):
    coordinator, config, _ = business_fleet
    secretary = submit(coordinator, config, key='pending-secretary', business_context=context())
    assert secretary['category'] == COMMERCIAL_PREPARATION_CATEGORY
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='pending-estimator', business_context=context('estimator'))
    assert error.value.status == 409


def test_verified_exact_catalog_allows_read_only_estimator_and_rechecks_claim(business_fleet):
    coordinator, config, _ = business_fleet
    readiness = config['projects']['synthetic-project']['business']['readiness']
    readiness['reconciliation_status'] = 'verified'
    estimator = submit(coordinator, config, key='ready-estimator', business_context=context('estimator'))
    assert estimator['access'] == 'read'
    claimed = coordinator.claim('worker-1', config['workers']['worker-1'])
    assert claimed['id'] == estimator['id']
    assert claimed['business_readiness'] == readiness
    assert claimed['business_template']['price_dependent'] is True


def test_changed_server_snapshot_prevents_price_dependent_claim(business_fleet):
    coordinator, config, _ = business_fleet
    readiness = config['projects']['synthetic-project']['business']['readiness']
    readiness['reconciliation_status'] = 'verified'
    estimator = submit(coordinator, config, key='stale-estimator', business_context=context('estimator'))
    readiness['revision'] = 'catalog-synthetic-r2'
    assert coordinator.claim('worker-1', config['workers']['worker-1']) is None
    assert coordinator.detail('founder', config['principals']['founder'], estimator['id'])['status'] == 'queued'


def test_business_child_cannot_gain_cto_write_access(business_fleet):
    coordinator, config, _ = business_fleet
    config['projects']['synthetic-project']['write'] = True
    config['principals']['founder']['write_projects'] = ['synthetic-project']
    parent = submit(coordinator, config, key='read-only-parent', business_context=context())
    with pytest.raises(Rejected) as error:
        submit(
            coordinator,
            config,
            key='forbidden-business-write',
            parent_id=parent['id'],
            logical_role='cto',
            stage='review',
            access='write',
        )
    assert error.value.status == 403


def test_worker_receives_delimited_context_and_writes_safe_provenance(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(
        ['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
         'commit', '--allow-empty', '-m', 'initial'],
        check=True,
        capture_output=True,
    )
    prompt_path = tmp_path / 'prompt.txt'
    cli = tmp_path / 'codex'
    cli.write_text(
        '#!/usr/bin/env python3\n'
        'import json, pathlib, sys\n'
        'pathlib.Path(%r).write_text(sys.stdin.read())\n'
        'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"prepared"}}))\n'
        % str(prompt_path)
    )
    cli.chmod(0o700)
    key = tmp_path / 'gateway.key'
    key.write_text('gateway-synthetic-secret')
    key.chmod(0o600)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    worker = Worker({
        'endpoint': 'http://127.0.0.1:4101',
        'token': 'worker-synthetic-token',
        'node_id': 'worker-1',
        'gateway_url': 'http://127.0.0.1:20128/v1',
        'gateway_key_file': str(key),
        'state_root': str(tmp_path / 'state'),
        'codex_path': str(cli),
        'allowed_roots': [str(root)],
        'artifacts_root': str(artifacts),
    })
    readiness = {
        'revision': 'catalog-synthetic-r1',
        'reconciliation_status': 'verified',
        'evidence_ref': 'catalog-evidence-synthetic-r1',
    }
    business_context = context()
    task = {
        'id': 'business-task',
        'attempt_id': 'business-attempt',
        'lease_token': 'lease-synthetic',
        'runtime': 'codex',
        'access': 'read',
        'category': COMMERCIAL_PREPARATION_CATEGORY,
        'root': str(root),
        'artifacts_root': str(artifacts),
        'brief': 'Prepare only; do not invent source records.',
        'business_context': business_context,
        'business_template': template_for('commercial-secretary'),
        'business_readiness': readiness,
    }
    reports = []
    worker.request = lambda route, body: reports.append(body) or {}
    worker.execute(task)
    terminal = reports[-1]
    artifact = json.loads(Path(terminal['artifact']['path']).read_text())
    prompt = prompt_path.read_text()
    assert terminal['type'] == 'succeeded'
    assert '<untrusted-business-task-data>' in prompt
    assert '"erp_access":"unverified"' in prompt
    assert 'Classify requests, documents and appointments' in prompt
    assert 'Never fabricate ERP data' in prompt
    assert artifact['provenance'] == {
        'domain_role': 'commercial-secretary',
        'business_context': business_context,
        'readiness': readiness,
        'erp_access': 'unverified',
    }


def test_bridge_preserves_normalized_business_scope_without_live_model(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, 'check_output', lambda args, **kwargs: '' if 'status' in args else 'synthetic-revision\n')
    key = tmp_path / 'gateway.key'
    key.write_text('gateway-synthetic-secret')
    key.chmod(0o600)
    bridge = Bridge({
        'token': 'bridge-synthetic-token',
        'hermes_root': '/synthetic/hermes',
        'hermes_revision': 'synthetic-revision',
        'hermes_python': '/synthetic/python',
        'gateway_key_file': str(key),
        'gateway_url': 'http://127.0.0.1:20128/v1',
    })
    model_result = json.dumps({
        'type': 'result',
        'exit_code': 0,
        'text': json.dumps({'summary': 'Prepared route', 'logical_role': 'dispatcher'}),
    }) + '\n'
    commands = []
    monkeypatch.setattr(
        subprocess,
        'run',
        lambda command, **kwargs: commands.append((command, kwargs)) or subprocess.CompletedProcess(command, 0, model_result, ''),
    )
    supplied = context()
    result = bridge.interpret({
        'title': 'Prepare',
        'brief': 'Use only the authorized references',
        'project': 'synthetic-project',
        'category': COMMERCIAL_PREPARATION_CATEGORY,
        'business_context': supplied,
    })
    assert result['business_context'] == supplied
    assert result['category'] == COMMERCIAL_PREPARATION_CATEGORY
    assert '<untrusted-authorized-task-data>' in commands[0][1]['input']
    assert '"instance_ref": "erp-synthetic-01"' in commands[0][1]['input']


def test_coordinator_rejects_a_bridge_response_that_changes_business_scope(business_fleet, monkeypatch):
    coordinator, config, _ = business_fleet
    config['hermes_bridge'] = {
        'url': 'http://127.0.0.1:4102',
        'token': 'bridge-synthetic-token',
        'timeout': 1,
    }
    changed = context(record_id='record-synthetic-02')
    payload = {
        'title': 'Prepare',
        'brief': 'Prepare a source-linked draft only',
        'project': 'synthetic-project',
        'category': COMMERCIAL_PREPARATION_CATEGORY,
        'logical_role': 'dispatcher',
        'summary': 'Prepared route',
        'hermes_revision': 'synthetic-revision',
        'business_context': changed,
    }

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            self.close()

    monkeypatch.setattr(
        coordinator_module.urllib.request,
        'urlopen',
        lambda *args, **kwargs: Response(json.dumps(payload).encode()),
    )
    with pytest.raises(Rejected) as error:
        submit(coordinator, config, key='changed-bridge-scope', business_context=context())
    assert error.value.status == 503
    assert coordinator.list_tasks('founder', config['principals']['founder']) == []


def test_cli_context_file_injects_domain_role_and_rejects_conflicts(tmp_path, monkeypatch):
    context_file = tmp_path / 'context.json'
    supplied = context()
    supplied.pop('domain_role')
    context_file.write_text(json.dumps(supplied))
    token_file = tmp_path / 'token'
    token_file.write_text('founder-synthetic-token')
    sent = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            self.close()

    monkeypatch.setattr(
        fleet_tasks.urllib.request,
        'urlopen',
        lambda request, timeout: sent.append(json.loads(request.data)) or Response(b'{}'),
    )
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'fleet_tasks.py', '--token-file', str(token_file), 'submit',
            '--project', 'synthetic-project', '--brief', 'Prepare',
            '--context-file', str(context_file), '--domain-role', 'commercial-secretary',
        ],
    )
    assert fleet_tasks.main() == 0
    assert sent[0]['category'] == COMMERCIAL_PREPARATION_CATEGORY
    assert sent[0]['business_context']['domain_role'] == 'commercial-secretary'

    supplied['domain_role'] = 'estimator'
    context_file.write_text(json.dumps(supplied))
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'fleet_tasks.py', '--token-file', str(token_file), 'submit',
            '--project', 'synthetic-project', '--brief', 'Prepare',
            '--context-file', str(context_file), '--domain-role', 'commercial-secretary',
        ],
    )
    with pytest.raises(SystemExit) as error:
        fleet_tasks.main()
    assert error.value.code == 2

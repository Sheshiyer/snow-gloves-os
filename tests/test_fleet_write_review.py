"""Manual read-only Sentinel review of a frozen CTO write artifact."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from lib.fleet_coordinator import Rejected
from lib.fleet_write_review import ReviewEvidenceError, evidence_from_artifact, validate_evidence
from test_fleet_coordinator import claim, fleet, report, submit
from test_fleet_write_worker import env as worker_env
from fleet_worker import Worker


PATCH = ('diff --git a/app.txt b/app.txt\n'
         '--- a/app.txt\n'
         '+++ b/app.txt\n'
         '@@ -1 +1 @@\n'
         '-old\n'
         '+new\n')
BASE = 'a' * 40


def enable(conf, review=True):
    conf['projects']['snowgloves']['write'] = True
    conf['projects']['snowgloves']['write_review_context'] = review
    conf['principals']['founder']['write_projects'] = ['snowgloves']


def artifact_envelope(task, **updates):
    patch = PATCH.encode()
    value = {
        'task_id': task['id'], 'attempt_id': task['attempt_id'], 'node': 'coding01',
        'runtime': 'codex', 'model': 'noesis-fast', 'output': 'Changed app behavior.',
        'access': 'write', 'base': BASE, 'files': ['app.txt'],
        'patch': {'text': PATCH, 'sha256': hashlib.sha256(patch).hexdigest(), 'bytes': len(patch)},
        'tests': [{'argv': ['python3', '-m', 'pytest'], 'exit_code': 0, 'tail': ''}],
    }
    value.update(updates)
    return value


def successful_artifact(c, conf, running, value=None, raw=None):
    path = c.artifacts / (running['id'] + '-' + running['attempt_id'] + '.json')
    if raw is None:
        raw = json.dumps(value if value is not None else artifact_envelope(running), separators=(',', ':')).encode()
    path.write_bytes(raw)
    report(c, conf, running, event_id='success-' + running['id'], type='succeeded',
           artifact={'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
    return path


def prepared_source(c, conf, *, value=None, raw=None):
    enable(conf)
    parent = submit(c, conf, idempotency_key='review-root')
    parent_run = claim(c, conf)
    root_artifact = c.artifacts / 'root.json'
    root_artifact.write_text(json.dumps({'task_id': parent['id'], 'attempt_id': parent_run['attempt_id']}))
    report(c, conf, parent_run, event_id='root-done', type='succeeded',
           artifact={'path': str(root_artifact), 'sha256': hashlib.sha256(root_artifact.read_bytes()).hexdigest()})
    source = submit(c, conf, parent_id=parent['id'], logical_role='cto', stage='review', access='write',
                    idempotency_key='write-source')
    source_run = claim(c, conf)
    assert source_run['id'] == source['id']
    artifact_path = successful_artifact(c, conf, source_run, value, raw)
    return parent, source, artifact_path


def submit_review(c, conf, parent, source, **updates):
    body = dict(parent_id=parent['id'], logical_role='sentinel', stage='verify', review_of=source['id'],
                idempotency_key='manual-review')
    body.update(updates)
    return submit(c, conf, **body)


def test_claim_delivers_only_verified_bounded_evidence_and_freezes_binding(fleet):
    c, conf, _ = fleet
    parent, source, source_path = prepared_source(c, conf)
    review = submit_review(c, conf, parent, source)
    assert review['review_of'] == source['id']
    binding = json.loads(c.db.execute('SELECT review_binding FROM tasks WHERE id=?', (review['id'],)).fetchone()[0])
    assert binding == {'task_id': source['id'], 'attempt_id': json.loads(source_path.read_text())['attempt_id'],
                       'artifact_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()}
    detail = c.detail('founder', conf['principals']['founder'], review['id'])
    assert 'review_evidence' not in detail
    assert 'patch' not in json.dumps(detail)
    claimed = claim(c, conf)
    evidence = claimed['review_evidence']
    assert claimed['review_of'] == source['id']
    assert evidence['task_id'] == source['id'] and evidence['attempt_id'] == binding['attempt_id']
    assert evidence['artifact_sha256'] == binding['artifact_sha256']
    assert evidence['base'] == BASE and evidence['files'] == ['app.txt']
    assert evidence['patch']['text'] == PATCH
    assert evidence['tests'] == [{'status': 'passed', 'exit_code': 0,
                                  'summary': 'Test command passed',
                                  'output_sha256': hashlib.sha256(b'').hexdigest()}]
    assert set(evidence) == {'schema', 'task_id', 'attempt_id', 'artifact_sha256', 'base', 'files', 'patch', 'tests'}
    assert not any(k in evidence for k in ('path', 'argv', 'output', 'raw'))


def test_review_is_default_off_and_requires_submit_and_read(fleet):
    c, conf, _ = fleet
    parent, source, _ = prepared_source(c, conf, value=artifact_envelope({'id': 'x', 'attempt_id': 'y'}))
    conf['projects']['snowgloves']['write_review_context'] = False
    with pytest.raises(Rejected) as exc:
        submit_review(c, conf, parent, source)
    assert exc.value.status == 403
    conf['projects']['snowgloves']['write_review_context'] = True
    conf['principals']['founder']['permissions'] = ['submit']
    with pytest.raises(Rejected) as exc:
        submit_review(c, conf, parent, source, idempotency_key='no-read')
    assert exc.value.status == 403
    conf['principals']['founder']['permissions'] = ['read']
    with pytest.raises(Rejected) as exc:
        submit_review(c, conf, parent, source, idempotency_key='no-submit')
    assert exc.value.status == 403


@pytest.mark.parametrize('updates', [
    {'logical_role': 'cto'}, {'stage': 'review'}, {'access': 'write'},
    {'runtime': 'claude'}, {'category': 'operations'},
])
def test_review_submission_requires_read_only_sentinel_verify_development_codex(fleet, updates):
    c, conf, _ = fleet
    parent, source, _ = prepared_source(c, conf)
    with pytest.raises(Rejected):
        submit_review(c, conf, parent, source, idempotency_key='invalid-' + str(updates), **updates)


@pytest.mark.parametrize('field,value', [
    ('status', 'failed'), ('access', 'read'), ('logical_role', 'sentinel'),
    ('category', 'operations'), ('runtime', 'claude'),
])
def test_only_succeeded_codex_development_cto_write_child_can_be_reviewed(fleet, field, value):
    c, conf, _ = fleet
    parent, source, _ = prepared_source(c, conf)
    c.db.execute('UPDATE tasks SET %s=? WHERE id=?' % field, (value, source['id']))
    c.db.commit()
    with pytest.raises(Rejected) as exc:
        submit_review(c, conf, parent, source, idempotency_key='wrong-source-' + field)
    assert exc.value.status == 409


def test_review_source_must_share_owner_project_and_parent(fleet):
    c, conf, _ = fleet
    parent, source, _ = prepared_source(c, conf)
    conf['principals']['reviewer'] = {'token': 'reviewer-secret-token', 'projects': ['snowgloves'],
                                      'permissions': ['read', 'submit']}
    with pytest.raises(Rejected):
        c.submit('reviewer', conf['principals']['reviewer'],
                 {'project': 'snowgloves', 'brief': 'review', 'runtime': 'codex',
                  'idempotency_key': 'different-owner', 'parent_id': parent['id'],
                  'logical_role': 'sentinel', 'stage': 'verify', 'review_of': source['id']})
    other_parent = submit(c, conf, idempotency_key='other-parent')
    with pytest.raises(Rejected):
        submit_review(c, conf, other_parent, source, idempotency_key='other-parent-review')

    c.db.execute("UPDATE tasks SET project='other-project' WHERE id=?", (source['id'],))
    c.db.commit()
    with pytest.raises(Rejected):
        submit_review(c, conf, parent, source, idempotency_key='other-project-review')


def test_review_cannot_widen_automatic_fanout_graph(fleet):
    c, conf, _ = fleet
    parent, source, _ = prepared_source(c, conf)
    c.db.execute('INSERT INTO fanout_plans(id,root_id,owner,project,plan_json,created) VALUES(?,?,?,?,?,?)',
                 ('f' * 32, parent['id'], 'founder', 'snowgloves', '{"children":[]}', 100.0))
    c.db.commit()
    with pytest.raises(Rejected) as exc:
        submit_review(c, conf, parent, source, idempotency_key='fanout-write-review')
    assert exc.value.status == 409


@pytest.mark.parametrize('kind', ['duplicate', 'nonfinite', 'utf8', 'hash', 'bytes', 'base', 'path', 'tests', 'large', 'large-artifact', 'secret'])
def test_malformed_or_unsafe_write_artifact_cannot_be_submitted_for_review(fleet, kind):
    c, conf, _ = fleet
    source_value = artifact_envelope({'id': 'x', 'attempt_id': 'y'})
    raw = None
    if kind == 'duplicate':
        raw = b'{"a":1,"a":2}'
    elif kind == 'nonfinite':
        raw = b'{"n":NaN}'
    elif kind == 'utf8':
        raw = b'\xff'
    elif kind == 'large-artifact':
        raw = b' ' * 1_000_001
    else:
        source_value = artifact_envelope({'id': 'x', 'attempt_id': 'y'})
        if kind == 'hash':
            source_value['patch']['sha256'] = '0' * 64
        elif kind == 'bytes':
            source_value['patch']['bytes'] = True
        elif kind == 'base':
            source_value['base'] = 'HEAD'
        elif kind == 'path':
            source_value['files'] = ['../app.txt']
        elif kind == 'tests':
            source_value['tests'][0]['exit_code'] = 1
        elif kind == 'large':
            large = 'diff --git a/app.txt b/app.txt\n' + 'x' * (65 * 1024)
            source_value['patch'] = {'text': large, 'sha256': hashlib.sha256(large.encode()).hexdigest(),
                                     'bytes': len(large.encode())}
        elif kind == 'secret':
            secret_patch = PATCH.replace('+new', '+founder-secret-token')
            source_value['patch'] = {'text': secret_patch,
                                     'sha256': hashlib.sha256(secret_patch.encode()).hexdigest(),
                                     'bytes': len(secret_patch.encode())}
    parent, source, _ = prepared_source(c, conf, value=source_value, raw=raw)
    with pytest.raises(Rejected) as exc:
        submit_review(c, conf, parent, source)
    assert exc.value.status == 409


@pytest.mark.parametrize('change', ['artifact', 'attempt', 'state', 'permission', 'project', 'flag', 'successor'])
def test_claim_revalidates_frozen_source_and_exposes_only_generic_hold(fleet, change):
    c, conf, _ = fleet
    parent, source, source_path = prepared_source(c, conf)
    review = submit_review(c, conf, parent, source)
    if change == 'artifact':
        source_path.write_text('{"tampered":true}')
    elif change == 'attempt':
        c.db.execute('UPDATE tasks SET attempt_id=? WHERE id=?', ('f' * 32, source['id']))
    elif change == 'state':
        c.db.execute('UPDATE tasks SET status=? WHERE id=?', ('failed', source['id']))
    elif change == 'permission':
        conf['principals']['founder']['permissions'] = ['submit']
    elif change == 'project':
        conf['principals']['founder']['projects'] = []
    elif change == 'flag':
        conf['projects']['snowgloves']['write_review_context'] = False
    else:
        c.db.execute('''INSERT INTO tasks(id,owner,project,title,brief,runtime,category,idem,request_hash,
                        status,created,updated,supersedes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     ('e' * 32, 'founder', 'snowgloves', 'retry', 'retry', 'other', 'development',
                      'superseding-review-test', '0' * 64, 'queued', 101.0, 101.0, source['id']))
    c.db.commit()
    assert claim(c, conf) is None
    conf['principals']['auditor'] = {'token': 'auditor-secret-token', 'projects': ['snowgloves'],
                                     'permissions': ['read'], 'view_owners': ['founder']}
    detail = c.detail('auditor', conf['principals']['auditor'], review['id'])
    graph = c.detail('auditor', conf['principals']['auditor'], parent['id'])['graph']
    assert detail['status'] == 'queued'
    assert detail['hold_reason'] == 'Review held: source or authorization checks require reconciliation.'
    child = next(item for item in graph['children'] if item['id'] == review['id'])
    assert child['hold_reason'] == detail['hold_reason']
    assert PATCH not in json.dumps(detail) and PATCH not in json.dumps(graph)
    assert PATCH not in json.dumps(c.list_tasks('auditor', conf['principals']['auditor']))
    assert PATCH not in json.dumps(c.detail('auditor', conf['principals']['auditor'], review['id'], events=True))


def test_idempotency_binds_review_of_and_frozen_attempt(fleet):
    c, conf, _ = fleet
    parent, source, _ = prepared_source(c, conf)
    first = submit_review(c, conf, parent, source)
    assert submit_review(c, conf, parent, source)['id'] == first['id']
    c.db.execute("UPDATE tasks SET status='cancelled' WHERE id=?", (first['id'],))
    c.db.commit()
    second = submit(c, conf, parent_id=parent['id'], logical_role='cto', stage='review', access='write',
                    idempotency_key='second-write')
    running = claim(c, conf)
    assert running['id'] == second['id']
    successful_artifact(c, conf, running)
    with pytest.raises(Rejected) as exc:
        submit_review(c, conf, parent, {'id': second['id']}, idempotency_key='manual-review')
    assert exc.value.status == 409
    c.db.execute('UPDATE tasks SET attempt_id=? WHERE id=?', ('f' * 32, source['id']))
    c.db.commit()
    with pytest.raises(Rejected):
        submit_review(c, conf, parent, source)


def test_shared_validator_rejects_duplicate_json_and_bad_closed_evidence():
    duplicate = b'{"a":1,"a":2}'
    with pytest.raises(ReviewEvidenceError):
        evidence_from_artifact(duplicate, 'a' * 32, 'b' * 32, hashlib.sha256(duplicate).hexdigest())
    value = {
        'schema': 'snowgloves.write-review.v1', 'task_id': 'a' * 32, 'attempt_id': 'b' * 32,
        'artifact_sha256': 'c' * 64, 'base': BASE, 'files': ['app.txt'],
        'patch': {'text': PATCH, 'sha256': hashlib.sha256(PATCH.encode()).hexdigest(), 'bytes': len(PATCH.encode())},
        'tests': [{'status': 'passed', 'exit_code': 0, 'summary': 'Test command passed',
                   'output_sha256': hashlib.sha256(b'').hexdigest()}],
    }
    assert validate_evidence(value) == value
    with pytest.raises(ReviewEvidenceError):
        validate_evidence(dict(value, surprise='extra'))
    bad = dict(value, tests=[dict(value['tests'][0], exit_code=True)])
    with pytest.raises(ReviewEvidenceError):
        validate_evidence(bad)
    nested_patch = PATCH.replace('app.txt', 'a/file.txt')
    nested = dict(value, files=['a/file.txt'], patch={
        'text': nested_patch, 'sha256': hashlib.sha256(nested_patch.encode()).hexdigest(),
        'bytes': len(nested_patch.encode()),
    })
    assert validate_evidence(nested)['files'] == ['a/file.txt']


def worker_evidence(root, patch=PATCH):
    patch = patch.replace('-old', '-one').replace('+new', '+two')
    patch_bytes = patch.encode()
    return {
        'schema': 'snowgloves.write-review.v1', 'task_id': 'c' * 32, 'attempt_id': 'd' * 32,
        'artifact_sha256': 'e' * 64, 'base': subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True).stdout.strip(),
        'files': ['app.txt'],
        'patch': {'text': patch, 'sha256': hashlib.sha256(patch_bytes).hexdigest(), 'bytes': len(patch_bytes)},
        'tests': [{'status': 'passed', 'exit_code': 0, 'summary': 'Test command passed',
                   'output_sha256': hashlib.sha256(b'').hexdigest()}],
    }


def test_git_accepts_misdirected_file_headers_but_review_rejects_them(worker_env):
    _config, _task, root, _tmp = worker_env
    (root / '.env').write_text('one\n')
    patch = PATCH.replace('-old', '-one').replace('+new', '+two')
    patch = patch.replace('--- a/app.txt', '--- a/.env').replace('+++ b/app.txt', '+++ b/.env')
    check = subprocess.run(['git', '-C', str(root), 'apply', '--check', '-'],
                           input=patch, text=True, capture_output=True)
    assert check.returncode == 0, check.stderr  # Git alone does not enforce the declared file list.
    with pytest.raises(ReviewEvidenceError, match='file headers'):
        validate_evidence(worker_evidence(root, patch))
    assert (root / '.env').read_text() == 'one\n'


@pytest.mark.parametrize('credential', ['AKIA' + '0' * 16, '-----BEGIN DSA PRIVATE KEY-----'])
def test_review_holds_additional_credential_formats(worker_env, credential):
    _config, _task, root, _tmp = worker_env
    with pytest.raises(ReviewEvidenceError, match='credential-like'):
        validate_evidence(worker_evidence(root, PATCH.replace('+new', '+' + credential)))


@pytest.mark.parametrize('metadata', [
    'new file mode 120000\n',
    'new file mode 160000\n',
    'index 1234567..7654321 120000\n',
    'rename from .env\nrename to app.txt\n',
    'copy from .env\ncopy to app.txt\n',
    'Binary files a/app.txt and b/app.txt differ\n',
    '--- a/app.txt\n',  # duplicate header
])
def test_review_rejects_unsupported_or_special_file_metadata(worker_env, metadata):
    _config, _task, root, _tmp = worker_env
    patch = PATCH.replace('--- a/app.txt\n', metadata + '--- a/app.txt\n', 1)
    with pytest.raises(ReviewEvidenceError):
        validate_evidence(worker_evidence(root, patch))


@pytest.mark.parametrize('kind', ['add', 'delete', 'executable', 'header-like-content'])
def test_review_supports_normal_git_patch_variants(worker_env, kind):
    _config, _task, root, _tmp = worker_env
    patch = PATCH
    if kind == 'add':
        patch = ('diff --git a/app.txt b/app.txt\nnew file mode 100644\n'
                 'index 0000000..1234567\n--- /dev/null\n+++ b/app.txt\n@@ -0,0 +1 @@\n+new\n')
    elif kind == 'delete':
        patch = ('diff --git a/app.txt b/app.txt\ndeleted file mode 100644\n'
                 'index 1234567..0000000\n--- a/app.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n')
    elif kind == 'executable':
        patch = 'diff --git a/app.txt b/app.txt\nold mode 100644\nnew mode 100755\n'
    else:
        patch = patch.replace('-old', '--- a/.env').replace('+new', '+++ b/.env')
    evidence = worker_evidence(root, patch)
    assert validate_evidence(evidence) == evidence


@pytest.mark.parametrize('state', ['failed', 'interrupted', 'cancelled', 'cancel_requested'])
def test_failed_parent_holds_existing_review_at_claim(fleet, state):
    c, conf, _ = fleet
    parent, source, _path = prepared_source(c, conf)
    review = submit_review(c, conf, parent, source)
    c.db.execute('UPDATE tasks SET status=? WHERE id=?', (state, parent['id']))
    c.db.commit()
    assert claim(c, conf) is None
    assert c.detail('founder', conf['principals']['founder'], review['id'])['hold_reason']


def review_task(task, evidence):
    return dict(task, access='read', category='development', logical_role='sentinel', stage='verify',
                parent_id='a' * 32, review_of=evidence['task_id'], review_evidence=evidence)


def test_worker_checks_exact_review_frame_and_creates_worktree_at_patch_base(worker_env):
    config, task, root, tmp = worker_env
    evidence = worker_evidence(root)
    task = review_task(task, evidence)
    capture = tmp / 'review-prompt.txt'
    cli = Path(config['codex_path'])
    cli.write_text('#!/usr/bin/env python3\nimport json,pathlib,sys\n'
                   'pathlib.Path(%r).write_text(sys.stdin.read())\n'
                   'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Read-only findings"}}))\n' % str(capture))
    cli.chmod(0o700)
    worker = Worker(config)
    reports = []
    worker.request = lambda route, body: reports.append(body) or {}
    assert 'read-only' in worker.command('/tmp/worktree', write=False)
    worker.execute(task)
    assert reports[-1]['type'] == 'succeeded', reports[-1].get('message')
    prompt = capture.read_text()
    assert 'BEGIN UNTRUSTED PATCH EVIDENCE JSON' in prompt
    assert 'END UNTRUSTED PATCH EVIDENCE JSON' in prompt
    assert '"text":"diff --git a/app.txt b/app.txt\\n' in prompt
    assert 'Do not apply or edit the patch' in prompt
    worktree = worker.state / 'worktrees' / (task['id'] + '-' + task['attempt_id'])
    actual_base = subprocess.run(['git', '-C', str(worktree), 'rev-parse', 'HEAD'],
                                 check=True, capture_output=True, text=True).stdout.strip()
    assert actual_base == evidence['base']
    payload = json.loads(Path(reports[-1]['artifact']['path']).read_text())
    assert payload['review_binding'] == {
        'review_of': evidence['task_id'], 'source_attempt_id': evidence['attempt_id'],
        'source_artifact_sha256': evidence['artifact_sha256'], 'base': evidence['base'],
        'patch_sha256': evidence['patch']['sha256'],
    }


@pytest.mark.parametrize('bad', ['missing', 'wrong-source', 'worker-secret', 'gateway-secret'])
def test_worker_rejects_missing_mismatched_or_credential_context_before_worktree(worker_env, bad):
    config, task, root, _tmp = worker_env
    evidence = worker_evidence(root)
    if bad == 'missing':
        task = dict(task, access='read', category='development', logical_role='sentinel', stage='verify',
                    parent_id='a' * 32, review_of=evidence['task_id'])
    else:
        if bad == 'wrong-source':
            evidence['task_id'] = 'b' * 32
        else:
            secret = 'worker-secret' if bad == 'worker-secret' else 'gateway-secret'
            patch = PATCH.replace('+new', '+' + secret)
            evidence = worker_evidence(root, patch)
        task = review_task(task, evidence)
        if bad == 'wrong-source':
            task['review_of'] = 'f' * 32
    worker = Worker(config)
    reports = []
    worker.request = lambda route, body: reports.append(body) or {}
    worker.execute(task)
    assert reports[-1]['type'] == 'failed'
    assert not (worker.state / 'worktrees').exists()


def test_worker_rejects_unavailable_base_before_worktree(worker_env):
    config, task, root, _tmp = worker_env
    evidence = worker_evidence(root)
    evidence['base'] = 'f' * 40
    task = review_task(task, evidence)
    worker = Worker(config)
    reports = []
    worker.request = lambda route, body: reports.append(body) or {}
    worker.execute(task)
    assert reports[-1]['type'] == 'failed'
    assert not (worker.state / 'worktrees').exists()


def test_worker_patch_check_blocks_runtime_for_inapplicable_patch(worker_env, monkeypatch):
    config, task, root, _tmp = worker_env
    invalid_patch = PATCH.replace('-old', '-not-in-base').replace('+new', '+two')
    task = review_task(task, worker_evidence(root, invalid_patch))
    worker = Worker(config)
    reports = []
    worker.request = lambda route, body: reports.append(body) or {}
    real_popen = subprocess.Popen
    launched = []
    def track_popen(*args, **kwargs):
        if args[0] and args[0][0] == config['codex_path']:
            launched.append(args[0])
        return real_popen(*args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', track_popen)
    worker.execute(task)
    assert reports[-1]['type'] == 'failed'
    assert launched == []


def test_task_cli_forwards_review_of_and_rejects_orphan_usage(monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fleet_tasks

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def read(self):
            return b'{}'
    seen = {}
    def urlopen(request, timeout=0):
        seen['request'] = request
        return Response()
    monkeypatch.setattr(fleet_tasks.urllib.request, 'urlopen', urlopen)
    monkeypatch.setenv('SNOWGLOVES_FLEET_TOKEN', 'founder-secret-token')
    source_id = 'd' * 32
    monkeypatch.setattr(sys, 'argv', ['fleet_tasks.py', 'submit', '--project', 'snowgloves', '--brief', 'review',
        '--parent', 'a' * 32, '--role', 'sentinel', '--stage', 'verify', '--review-of', source_id])
    assert fleet_tasks.main() == 0
    assert json.loads(seen['request'].data)['review_of'] == source_id
    monkeypatch.setattr(sys, 'argv', ['fleet_tasks.py', 'submit', '--project', 'snowgloves', '--brief', 'review',
        '--review-of', source_id])
    with pytest.raises(SystemExit):
        fleet_tasks.main()
    assert '--review-of require --parent' in capsys.readouterr().err


def test_review_schema_migrates_legacy_task_rows_without_rebinding(tmp_path):
    data_root = tmp_path / 'legacy-ops'
    data_root.mkdir()
    db = sqlite3.connect(data_root / 'fleet.sqlite3')
    db.execute('''CREATE TABLE tasks (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, project TEXT NOT NULL,
        title TEXT NOT NULL, brief TEXT NOT NULL, runtime TEXT NOT NULL,
        category TEXT NOT NULL, idem TEXT NOT NULL, request_hash TEXT NOT NULL,
        status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
        worker TEXT, attempt_id TEXT, lease_hash TEXT, deadline REAL,
        artifact TEXT, logical_role TEXT NOT NULL DEFAULT 'cto', UNIQUE(owner, idem))''')
    db.execute('''INSERT INTO tasks(id,owner,project,title,brief,runtime,category,idem,
                  request_hash,status,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
               ('1' * 32, 'founder', 'snowgloves', 'old task', 'old brief', 'codex',
                'development', 'legacy-idem', 'a' * 64, 'succeeded', 1.0, 2.0))
    db.commit()
    db.close()
    config = {'data_root': str(data_root), 'projects': {}, 'principals': {}, 'workers': {}}
    from lib.fleet_coordinator import Coordinator
    c = Coordinator(config)
    try:
        columns = {row[1] for row in c.db.execute('PRAGMA table_info(tasks)')}
        assert {'review_of', 'review_binding', 'parent_id', 'stage', 'access'} <= columns
        old = c.db.execute('SELECT * FROM tasks WHERE id=?', ('1' * 32,)).fetchone()
        assert old['review_of'] is None and old['review_binding'] is None
        assert old['parent_id'] is None and old['access'] == 'read'
        assert old['status'] == 'succeeded' and old['attempt_id'] is None
    finally:
        c.close()

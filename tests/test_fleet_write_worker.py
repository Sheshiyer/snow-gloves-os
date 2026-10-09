"""Write adapter contract: sandboxed edit, worker-computed reviewable patch, gates, tests. Fake CLI only."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_worker import Worker

FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
cwd = pathlib.Path(sys.argv[sys.argv.index('-C') + 1])
for line in sys.stdin.read().splitlines():
    if line.startswith('WRITE '):
        _, path, content = line.split(' ', 2)
        target = cwd / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.replace('\\\\n', '\\n'))
    elif line.startswith('LINK '):
        _, path, dest = line.split(' ', 2)
        os.symlink(dest, cwd / path)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "edited gateway-secret"}}))
'''
PASS = {'argv': [sys.executable, '-c', 'import sys; sys.exit(0)']}


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def env(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'app.txt').write_text('one\n')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'initial')
    key = tmp_path / 'key'
    key.write_text('gateway-secret')
    key.chmod(0o600)
    cli = tmp_path / 'codex'
    cli.write_text(FAKE)
    cli.chmod(0o700)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    config = dict(endpoint='http://127.0.0.1:4101', token='worker-secret', node_id='coding01',
                  gateway_url='http://127.0.0.1:20128/v1', gateway_key_file=str(key),
                  state_root=str(tmp_path / 'state'), codex_path=str(cli),
                  allowed_roots=[str(root)], artifacts_root=str(artifacts),
                  write_roots=[str(root)], test_commands={str(root): [PASS]})
    task = dict(id='task1', attempt_id='attempt1', lease_token='lease-secret', runtime='codex', access='write',
                root=str(root), artifacts_root=str(artifacts), brief='WRITE app.txt one\\ntwo')
    return config, task, root, tmp_path


def run(config, task):
    worker = Worker(config)
    reports = []
    worker.request = lambda route, body: reports.append(body) or {}
    worker.execute(task)
    return worker, reports[-1]


def test_sandbox_is_workspace_write_only_for_write_tasks(env):
    config, _, _, _ = env
    worker = Worker(config)
    assert 'workspace-write' in worker.command('/tmp/w', write=True) and 'read-only' not in worker.command('/tmp/w', write=True)
    assert 'read-only' in worker.command('/tmp/w') and 'workspace-write' not in worker.command('/tmp/w')
    assert 'sandbox_workspace_write.network_access=false' in worker.command('/tmp/w', write=True)


def test_write_task_returns_a_reviewable_patch_and_test_evidence(env):
    config, task, root, tmp = env
    worker, final = run(config, task)
    assert final['type'] == 'succeeded', final.get('message')
    path = Path(final['artifact']['path'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == final['artifact']['sha256']
    art = json.loads(path.read_text())
    assert art['access'] == 'write' and art['files'] == ['app.txt']
    assert art['base'] == git(root, 'rev-parse', 'HEAD').strip()
    assert art['tests'] == [{'argv': PASS['argv'], 'exit_code': 0, 'tail': ''}]
    assert hashlib.sha256(art['patch']['text'].encode()).hexdigest() == art['patch']['sha256']
    # the patch applies cleanly to an untouched clone; nothing was applied to the source repo
    clone = tmp / 'clone'
    subprocess.run(['git', 'clone', '-q', str(root), str(clone)], check=True)
    (tmp / 'p.patch').write_text(art['patch']['text'])
    git(clone, 'apply', '--check', str(tmp / 'p.patch'))
    assert (root / 'app.txt').read_text() == 'one\n' and git(root, 'status', '--porcelain') == ''
    assert 'gateway-secret' not in art['output'] and not worker.active.exists()


@pytest.mark.parametrize('mutate,reason', [
    (lambda c, t: c.pop('write_roots'), 'Write is not enabled'),
    (lambda c, t: c.update(write_roots=['/elsewhere']), 'Write is not enabled'),
    (lambda c, t: c.update(test_commands={}), 'Write is not enabled'),
])
def test_write_requires_worker_side_enablement_before_anything_starts(env, mutate, reason):
    config, task, _, _ = env
    mutate(config, task)
    worker, final = run(config, task)
    assert final['type'] == 'failed' and reason in final['message']
    assert not (worker.state / 'worktrees').exists()


@pytest.mark.parametrize('brief,reason', [
    ('WRITE .env SECRET=1', 'denied path'),
    ('WRITE sub/.env.local X=1', 'denied path'),
    ('WRITE .github/workflows/ci.yml on:push', 'denied path'),
    ('WRITE keys/server.pem x', 'denied path'),
    ('LINK evil /etc/passwd', 'symlink'),
    ('WRITE leak.txt key sk-abcdefgh12345678', 'credential'),
    ('WRITE leak.txt gateway-secret', 'credential'),
    ('WRITE leak.txt worker-secret', 'credential'),
    ('WRITE leak.txt -----BEGIN PRIVATE KEY-----', 'credential'),
    ('NOOP', 'No changes'),
])
def test_patch_gates_reject_without_an_artifact_or_retained_patch(env, brief, reason):
    config, task, root, _ = env
    task['brief'] = brief
    worker, final = run(config, task)
    assert final['type'] == 'failed' and reason in final['message']
    assert 'artifact' not in final
    assert not list((worker.state / 'patches').glob('*')) if (worker.state / 'patches').exists() else True
    assert git(root, 'status', '--porcelain') == ''


def test_oversized_patch_is_rejected(env):
    config, task, _, _ = env
    config['max_patch_bytes'] = 50
    task['brief'] = 'WRITE big.txt ' + 'x' * 500
    _, final = run(config, task)
    assert final['type'] == 'failed' and 'too large' in final['message']


def test_failing_tests_fail_the_task_but_keep_the_patch_privately(env):
    config, task, _, _ = env
    config['test_commands'] = {config['write_roots'][0]: [PASS, {'argv': [sys.executable, '-c', 'print("boom"); raise SystemExit(3)']}]}
    worker, final = run(config, task)
    assert final['type'] == 'failed' and 'exit 3' in final['message'] and 'artifact' not in final
    kept = worker.state / 'patches' / 'attempt1.patch'
    assert 'two' in kept.read_text() and kept.stat().st_mode & 0o077 == 0


def test_tests_that_modify_the_tree_fail_the_task(env):
    config, task, _, _ = env
    config['test_commands'] = {config['write_roots'][0]: [{'argv': [sys.executable, '-c', 'open("stray.txt","w").write("x")']}]}
    _, final = run(config, task)
    assert final['type'] == 'failed' and 'modified the working tree' in final['message']


def test_read_tasks_ignore_write_machinery(env):
    config, task, _, _ = env
    task['access'] = 'read'
    config.pop('write_roots')
    task['brief'] = 'WRITE app.txt hacked'
    _, final = run(config, task)
    art = json.loads(Path(final['artifact']['path']).read_text())
    assert final['type'] == 'succeeded' and 'patch' not in art and art.get('access', 'read') == 'read'

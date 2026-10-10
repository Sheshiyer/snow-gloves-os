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
    (root / 'verify.py').write_text('print("ok")\n')
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
    command = worker.command('/tmp/w', write=True)
    disabled = [command[index + 1] for index, arg in enumerate(command) if arg == '--disable']
    assert {'multi_agent', 'multi_agent_v2'} <= set(disabled)


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


# --- ISC-383: verification runs proposed code, so it must be confined by the OS, not by argv or cwd ---
needs_sandbox = pytest.mark.skipif(not Path('/usr/bin/sandbox-exec').exists(), reason='macOS Seatbelt required')


def verify_with(config, code):
    """Make the agent edit the tracked verify.py, which the unchanged allowlisted command then executes."""
    root = config['write_roots'][0]
    config['test_commands'] = {root: [{'argv': [sys.executable, 'verify.py']}]}
    return 'WRITE verify.py ' + code.replace('\n', '\\n')


@needs_sandbox
def test_edited_verification_script_cannot_write_outside_the_worktree(env):
    config, task, _, tmp = env
    marker = tmp / 'outside' / 'marker.txt'
    marker.parent.mkdir()
    marker.write_bytes(b'original')
    for swallow in (False, True):  # a script that hides the denial must not change the outcome on disk
        code = 'import pathlib\ntry:\n    pathlib.Path(%r).write_text("pwned")\nexcept Exception:\n    %s' % (str(marker), 'pass' if swallow else 'raise')
        task['brief'] = verify_with(config, code)
        task['attempt_id'] = 'attempt-%s' % swallow
        worker, final = run(config, task)
        assert marker.read_bytes() == b'original'
        if not swallow:
            assert final['type'] == 'failed' and 'Tests failed' in final['message'] and 'artifact' not in final


@needs_sandbox
def test_verification_cannot_reach_the_network_but_may_use_loopback(env):
    config, task, _, _ = env
    external = 'import socket,sys\ntry:\n    socket.create_connection(("1.1.1.1", 80), timeout=3)\n    sys.exit(7)\nexcept OSError:\n    pass'
    task['brief'] = verify_with(config, external)
    _, final = run(config, task)
    assert final['type'] == 'succeeded', final.get('message')  # exit 7 would mean the connection was possible
    loopback = 'import socket\ns = socket.socket()\ns.bind(("127.0.0.1", 0))\ns.listen()\nsocket.create_connection(s.getsockname(), timeout=3).close()'
    task['brief'] = verify_with(config, loopback)
    task['attempt_id'] = 'attempt-loop'
    _, final = run(config, task)
    assert final['type'] == 'succeeded', final.get('message')


@needs_sandbox
def test_verification_cannot_read_denied_locations(env):
    config, task, _, tmp = env
    secret = tmp / 'secrets' / 'key.txt'
    secret.parent.mkdir()
    secret.write_text('SECRETDATA')
    code = 'import sys\ntry:\n    open(%r).read()\nexcept OSError:\n    sys.exit(5)' % str(secret)
    config['verify_deny_read'] = [str(secret.parent)]
    task['brief'] = verify_with(config, code)
    _, final = run(config, task)
    assert final['type'] == 'failed' and 'exit 5' in final['message']
    config['verify_deny_read'] = []  # positive control: without the deny rule the same script succeeds
    config['test_commands'] = {config['write_roots'][0]: [{'argv': [sys.executable, 'verify.py']}]}
    task['attempt_id'] = 'attempt-control'
    _, final = run(config, task)
    assert final['type'] == 'succeeded', final.get('message')


def test_missing_sandbox_fails_closed_before_running_any_test(env):
    config, task, _, tmp = env
    marker = tmp / 'ran.txt'
    config['sandbox_exec_path'] = str(tmp / 'no-such-sandbox')
    config['test_commands'] = {config['write_roots'][0]: [{'argv': [sys.executable, '-c', 'open(%r, "w").write("x")' % str(marker)]}]}
    _, final = run(config, task)
    assert final['type'] == 'failed' and 'sandbox is unavailable' in final['message']
    assert not marker.exists() and 'artifact' not in final


@needs_sandbox
def test_verification_gets_a_private_home_and_temp(env):
    config, task, _, _ = env
    code = 'import os,sys\\nsys.exit(0 if os.environ["HOME"] == os.environ["TMPDIR"] and "verify-tmp" in os.environ["HOME"] else 9)'
    task['brief'] = verify_with(config, code)
    _, final = run(config, task)
    assert final['type'] == 'succeeded', final.get('message')


@needs_sandbox
def test_only_listed_python_library_paths_are_readable_inside_a_denied_area(env):
    config, task, _, tmp = env
    area = tmp / 'denied'
    (area / 'lib').mkdir(parents=True)
    (area / 'lib' / 'allowedmod.py').write_text('VALUE = 1\n')
    (area / 'other.txt').write_text('private')
    config['verify_deny_read'] = [str(area)]
    code = 'import sys\nimport allowedmod\ntry:\n    open(%r).read()\n    sys.exit(4)\nexcept OSError:\n    pass' % str(area / 'other.txt')
    task['brief'] = verify_with(config, code)
    _, final = run(config, task)
    assert final['type'] == 'failed'  # not importable without the explicit path
    config['verify_python_paths'] = [str(area / 'lib')]
    task['attempt_id'] = 'attempt-lib'
    _, final = run(config, task)
    assert final['type'] == 'succeeded', final.get('message')  # library readable, sibling file still denied


@needs_sandbox
def test_verification_cannot_signal_processes_outside_its_sandbox_but_may_manage_its_own(env):
    config, task, _, _ = env
    outsider = subprocess.Popen(['sleep', '60'])
    try:
        code = ('import os, signal, subprocess, sys, time\n'
                'p = subprocess.Popen(["sleep", "30"], start_new_session=True)\n'
                'time.sleep(0.2)\n'
                'os.killpg(p.pid, signal.SIGTERM)\n'
                'p.wait(timeout=5)\n'
                'try:\n    os.kill(%d, signal.SIGTERM)\n    sys.exit(6)\nexcept PermissionError:\n    pass' % outsider.pid)
        task['brief'] = verify_with(config, code)
        _, final = run(config, task)
        assert final['type'] == 'succeeded', final.get('message')
        assert outsider.poll() is None  # still running
    finally:
        outsider.kill()
        outsider.wait()

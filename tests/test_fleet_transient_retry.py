"""A 429 before any command or edit ran has a certain outcome (nothing happened), so one bounded retry is safe.
Anything that ran, or any other failure, is never replayed."""
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_worker import Worker

# Each invocation consumes the next mode from modes.json next to the script.
FAKE = '''#!/usr/bin/env python3
import json, pathlib, sys
here = pathlib.Path(__file__).parent
sys.stdin.read()
state = json.loads((here / 'modes.json').read_text())
mode = state['modes'][min(state['calls'], len(state['modes']) - 1)]
state['calls'] += 1
(here / 'modes.json').write_text(json.dumps(state))
def emit(row): print(json.dumps(row), flush=True)
emit({"type": "item.completed", "item": {"type": "reasoning", "text": "thinking"}})
if mode == 'ok':
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}})
elif mode == 'ok-after-command':
    emit({"type": "item.started", "item": {"type": "command_execution", "command": "ls"}})
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}})
elif mode == '429':
    emit({"type": "error", "message": "exceeded retry limit, last status: 429 Too Many Requests, request id: x"})
    emit({"type": "turn.failed", "error": {"message": "exceeded retry limit, last status: 429 Too Many Requests"}})
    sys.exit(1)
elif mode == '429-after-command':
    emit({"type": "item.started", "item": {"type": "command_execution", "command": "touch x"}})
    emit({"type": "item.completed", "item": {"type": "command_execution", "command": "touch x", "exit_code": 0}})
    emit({"type": "turn.failed", "error": {"message": "exceeded retry limit, last status: 429 Too Many Requests"}})
    sys.exit(1)
elif mode == 'other-failure':
    emit({"type": "turn.failed", "error": {"message": "model refused the request"}})
    sys.exit(1)
'''


@pytest.fixture
def env(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'init'], check=True)
    key = tmp_path / 'key'
    key.write_text('gateway-secret')
    key.chmod(0o600)
    cli = tmp_path / 'codex'
    cli.write_text(FAKE)
    cli.chmod(0o700)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    config = dict(endpoint='http://127.0.0.1:4101', token='worker-secret', node_id='n', gateway_url='http://127.0.0.1:20128/v1',
                  gateway_key_file=str(key), state_root=str(tmp_path / 'state'), codex_path=str(cli),
                  allowed_roots=[str(root)], artifacts_root=str(artifacts), transient_backoff=0)
    task = dict(id='task1', attempt_id='attempt1', lease_token='lease', runtime='codex', root=str(root), artifacts_root=str(artifacts), brief='Review')

    def run(modes, request=None, **overrides):
        (tmp_path / 'modes.json').write_text(json.dumps({'modes': modes, 'calls': 0}))
        worker = Worker({**config, **overrides})
        reports = []
        worker.request = (lambda route, body: reports.append(body) or (request(body) if request else {}))
        worker.execute(dict(task))
        return worker, reports, json.loads((tmp_path / 'modes.json').read_text())['calls']
    return run, tmp_path


def terminal(reports):
    return [r for r in reports if r['type'] != 'heartbeat'][-1]


def test_a_429_before_any_effect_is_retried_and_can_then_succeed(env):
    run, _ = env
    _, reports, calls = run(['429', 'ok'])
    assert calls == 2 and terminal(reports)['type'] == 'succeeded'


def test_retries_are_bounded(env):
    run, _ = env
    _, reports, calls = run(['429'], transient_retries=2)
    assert calls == 3 and terminal(reports)['type'] == 'failed'


def test_retries_can_be_disabled(env):
    run, _ = env
    _, reports, calls = run(['429', 'ok'], transient_retries=0)
    assert calls == 1 and terminal(reports)['type'] == 'failed'


def test_default_allows_two_retries(env):
    run, _ = env
    _, reports, calls = run(['429', '429', 'ok'])
    assert calls == 3 and terminal(reports)['type'] == 'succeeded'


def test_a_429_after_a_command_ran_is_never_replayed(env):
    run, _ = env
    _, reports, calls = run(['429-after-command', 'ok'])
    assert calls == 1 and terminal(reports)['type'] == 'failed'


def test_non_transient_failures_are_not_retried(env):
    run, _ = env
    _, reports, calls = run(['other-failure', 'ok'])
    assert calls == 1 and terminal(reports)['type'] == 'failed'


def test_a_successful_first_run_is_never_repeated(env):
    run, _ = env
    _, reports, calls = run(['ok-after-command', 'ok'])
    assert calls == 1 and terminal(reports)['type'] == 'succeeded'


def test_each_attempt_keeps_its_own_log_and_the_artifact_comes_from_the_last_run(env):
    run, tmp = env
    worker, reports, _ = run(['429', 'ok'])
    logs = sorted(p.name for p in worker.state.glob('*.jsonl'))
    assert logs == ['attempt1.jsonl', 'attempt1.retry1.jsonl']
    artifact = json.loads(Path(terminal(reports)['artifact']['path']).read_text())
    assert artifact['output'] == 'done'


def test_cancellation_during_backoff_stops_without_another_run(env):
    run, tmp = env

    def cancel_once_the_first_run_has_started(body):
        calls = json.loads((tmp / 'modes.json').read_text())['calls']
        return {'cancel_requested': body['type'] == 'heartbeat' and calls >= 1}
    _, reports, calls = run(['429', 'ok'], request=cancel_once_the_first_run_has_started, transient_backoff=30)
    assert calls == 1 and terminal(reports)['type'] == 'cancelled'


def test_stopping_the_worker_during_backoff_interrupts_for_reconciliation(env):
    run, tmp = env
    holder = {}

    def stop_worker(body):
        calls = json.loads((tmp / 'modes.json').read_text())['calls']
        if calls >= 1 and 'worker' in holder:
            holder['worker'].stopping = True
        return {}
    import fleet_worker
    original = fleet_worker.Worker.execute

    def capture(self, task):
        holder['worker'] = self
        return original(self, task)
    fleet_worker.Worker.execute = capture
    try:
        _, reports, calls = run(['429', 'ok'], request=stop_worker, transient_backoff=30)
    finally:
        fleet_worker.Worker.execute = original
    assert calls == 1 and terminal(reports)['type'] == 'interrupted'

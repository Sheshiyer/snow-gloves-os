"""Execution contract tests use fake CLIs, never provider credentials."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fleet_worker import Worker, private_json, stop_group
from fleet_hermes_bridge import Bridge, server


@pytest.fixture
def worker(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git','init',str(root)],check=True,capture_output=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--allow-empty','-m','initial'],check=True,capture_output=True)
    key = tmp_path / 'key'
    key.write_text('gateway-secret')
    key.chmod(0o600)
    cli = tmp_path / 'codex'
    cli.write_text('#!/usr/bin/env python3\nimport json,sys\nsys.stdin.read()\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"done gateway-secret"}}))\n')
    cli.chmod(0o700)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    w = Worker(dict(endpoint='http://127.0.0.1:4101',token='worker-secret',node_id='coding01',
                    gateway_url='http://127.0.0.1:20128/v1',gateway_key_file=str(key),
                    state_root=str(tmp_path/'state'), codex_path=str(cli),
                    allowed_roots=[str(root)], artifacts_root=str(artifacts)))
    task = dict(id='task1',attempt_id='attempt1',lease_token='lease-secret',runtime='codex',
                root=str(root),artifacts_root=str(artifacts),brief='Review repository')
    return w, task


def test_worker_artifact_and_explicit_route(worker):
    w, task = worker
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    terminal = reports[-1]
    assert terminal['type'] == 'succeeded'
    path = Path(terminal['artifact']['path'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == terminal['artifact']['sha256']
    assert json.loads(path.read_text())['output'] == 'done [REDACTED]'
    assert not w.active.exists() and not w.pending.exists()
    command = w.command('/tmp/worktree')
    assert '--ignore-user-config' in command and 'read-only' in command
    assert 'model_provider="omniroute"' in command
    assert command[-1] == '-'
    assert path.stat().st_mode & 0o077 == 0


def test_worker_rejects_root_without_starting(worker):
    w, task = worker
    task['root'] = '/tmp'
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'failed'
    assert not (w.state/'worktrees').exists()


def test_terminal_retry_never_reexecutes(worker):
    w, task = worker
    def offline(route, body):
        raise OSError('offline')
    w.request = offline
    w.execute(task)
    assert w.pending.exists()
    terminal = json.loads(w.pending.read_text())
    event_id = terminal['event_id']
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    assert w.flush()
    assert reports[-1]['event_id'] == event_id
    assert reports[-1]['type'] == 'succeeded'


def test_worker_restart_reports_interrupted(worker):
    w, task = worker
    private_json(w.active, task)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.recover()
    assert reports[-1]['type'] == 'interrupted'


def test_cancel_terminates_running_group(worker):
    w, task = worker
    Path(w.config['codex_path']).write_text('#!/usr/bin/env python3\nimport time,sys\nsys.stdin.read()\ntime.sleep(60)\n')
    reports = []
    def report(route, body):
        reports.append(body)
        return {'cancel_requested': body['type'] == 'heartbeat'}
    w.request = report
    w.execute(task)
    assert reports[-1]['type'] == 'cancelled'
    assert not w.pending.exists()


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess,'check_output',lambda *args,**kwargs:'revision\n')
    key = tmp_path/'key'
    key.write_text('gateway-secret')
    key.chmod(0o600)
    return Bridge(dict(token='bridge-secret',hermes_root='/hermes',hermes_revision='revision',
                       hermes_python='/python',hermes_profile='snowgloves',gateway_key_file=str(key),
                       gateway_url='http://127.0.0.1:20128/v1'))


def test_bridge_preserves_request_identity_and_disables_tools(bridge, monkeypatch):
    commands = []
    def fake(command, **kwargs):
        commands.append((command,kwargs))
        return subprocess.CompletedProcess(command,0,json.dumps({'type':'result','exit_code':0,'text':json.dumps({'summary':'Ready','logical_role':'interpreter'})})+'\n','')
    monkeypatch.setattr(subprocess,'run',fake)
    body = dict(title='Review',brief='Original instruction',project='snowgloves')
    result = bridge.interpret(body)
    assert result['brief'] == body['brief'] and result['project'] == body['project']
    command, kwargs = commands[0]
    assert 'snowgloves-none' in command and '--safe-mode' in command
    assert kwargs['env']['OPENAI_BASE_URL'] == 'http://127.0.0.1:20128/v1'
    assert 'create_custom_toolset' in command[2]


def test_bridge_rejects_model_authority_override(bridge, monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda command,**kwargs: subprocess.CompletedProcess(command,0,
                        json.dumps({'type':'result','exit_code':0,'text':json.dumps({'summary':'done','logical_role':'interpreter','project':'another'})}),'') )
    with pytest.raises(ValueError):
        bridge.interpret(dict(title='x',brief='x',project='snowgloves'))


def test_bridge_rejects_tool_execution(bridge, monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda command,**kwargs: subprocess.CompletedProcess(command,0,json.dumps({'type':'tool_use','name':'terminal'}),'') )
    with pytest.raises(ValueError):
        bridge.interpret(dict(title='x',brief='x',project='snowgloves'))


def test_bridge_http_auth_and_origin(bridge):
    http = server(bridge, 0)
    thread = threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    url = 'http://127.0.0.1:'+str(http.server_port)+'/interpret'
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url,data=b'{}'),timeout=2)
        assert error.value.code == 401
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url,data=b'{}',headers={'Authorization':'Bearer bridge-secret','Origin':'https://example.invalid'}),timeout=2)
        assert error.value.code == 403
    finally:
        http.shutdown()
        http.server_close()


def test_services_load_own_private_config(tmp_path):
    from fleet_worker import load_config as load_worker
    from fleet_hermes_bridge import load_config as load_bridge
    path = tmp_path/'config.json'
    private_json(path, {'endpoint':'http://127.0.0.1:4101'})
    assert load_worker(path)['endpoint'] == load_bridge(path)['endpoint']
    path.chmod(0o644)
    for load in (load_worker,load_bridge):
        with pytest.raises(ValueError):
            load(path)


def test_runtime_environment_excludes_inherited_secrets(monkeypatch):
    from fleet_worker import runtime_environment
    monkeypatch.setenv('OPENAI_API_KEY','should-not-inherit')
    monkeypatch.setenv('ANTHROPIC_API_KEY','should-not-inherit')
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN','should-not-inherit')
    assert not any(key in runtime_environment() for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','CLOUDFLARE_API_TOKEN'))


def test_bridge_rejects_duplicate_json(bridge):
    http = server(bridge,0)
    thread = threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    try:
        request = Request('http://127.0.0.1:'+str(http.server_port)+'/interpret',
                          data=b'{"title":"a","title":"b"}',
                          headers={'Authorization':'Bearer bridge-secret'})
        with pytest.raises(HTTPError) as error:
            urlopen(request,timeout=2)
        assert error.value.code == 422
    finally:
        http.shutdown()
        http.server_close()


def test_worker_entrypoint_uses_worker_config(worker, tmp_path):
    w, _ = worker
    config = tmp_path/'worker.json'
    private_json(config,w.config)
    process = subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/fleet_worker.py'), '--config',str(config)],
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        import time
        deadline = time.monotonic()+3
        while not (w.state/'worker.lock').exists() and process.poll() is None and time.monotonic()<deadline:
            time.sleep(.02)
        assert process.poll() is None
        assert (w.state/'worker.lock').exists()
    finally:
        process.terminate()
        process.communicate(timeout=5)

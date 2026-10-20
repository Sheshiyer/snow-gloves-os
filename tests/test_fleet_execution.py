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
from fleet_hermes_bridge import Bridge, server, verify_hermes_checkout


@pytest.fixture
def worker(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    subprocess.run(['git','init',str(root)],check=True,capture_output=True)
    # Owned by tenant-a, so the tenant-isolated cases below have a verifiable history.
    (root / 'MANIFEST.yaml').write_text('tenant: tenant-a\n')
    subprocess.run(['git','-C',str(root),'add','MANIFEST.yaml'],check=True,capture_output=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','initial'],check=True,capture_output=True)
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
    task = dict(project='snowgloves', id='task1',attempt_id='attempt1',lease_token='lease-secret',runtime='codex',
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
    assert command[1:3] == ['exec', '--ignore-user-config']
    assert '--ignore-user-config' in command and 'read-only' in command
    disabled = [command[index + 1] for index, arg in enumerate(command) if arg == '--disable']
    assert {'multi_agent', 'multi_agent_v2'} <= set(disabled)
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


def test_worker_rechecks_a_tenant_root_before_every_task(worker):
    w, task = worker
    root = Path(task['root']).resolve()
    w.tenant_roots = {root: 'tenant-a'}
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'succeeded'
    # A later fetch brings another tenant's tree into the object database.
    os.makedirs(root / 'tenants' / 'other-tenant')
    (root / 'tenants' / 'other-tenant' / 'MANIFEST.yaml').write_text('tenant: other-tenant')
    subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    'commit', '-m', 'fetched'], check=True, capture_output=True)
    task = dict(task, id='task2', attempt_id='attempt2')
    w.execute(task)
    # Refused before any worktree exists; the reason stays in private worker state.
    assert reports[-1]['type'] == 'failed'
    assert not (w.state / 'worktrees' / 'task2-attempt2').exists()


def test_worker_rechecks_admitted_tenant_projects_without_local_config(worker):
    w, task = worker
    root = Path(task['root']).resolve()
    assert w.tenant_roots == {}
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(dict(task, tenant='tenant-a', tenant_isolated=True))
    assert reports[-1]['type'] == 'succeeded'
    (root / 'fleet.yaml').write_text('every tenant')
    subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    'commit', '-m', 'fetched'], check=True, capture_output=True)
    w.execute(dict(task, id='task2', attempt_id='attempt2', tenant='tenant-a', tenant_isolated=True))
    assert reports[-1]['type'] == 'failed'
    assert not (w.state / 'worktrees' / 'task2-attempt2').exists()
    # A local tenant_roots entry that names a different tenant refuses the assignment.
    (root / 'fleet.yaml').unlink()
    w.tenant_roots = {root: 'tenant-b'}
    w.execute(dict(task, id='task3', attempt_id='attempt3', tenant='tenant-a', tenant_isolated=True))
    assert reports[-1]['type'] == 'failed'


def test_worker_never_runs_repository_hooks_when_creating_a_worktree(worker, tmp_path):
    w, task = worker
    root = Path(task['root']).resolve()
    marker = tmp_path / 'hook-ran'
    hook = root / '.git' / 'hooks' / 'post-checkout'
    hook.write_text('#!/bin/sh\ntouch %s\n' % marker)
    hook.chmod(0o755)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'succeeded'
    assert not marker.exists()


def test_tenant_tasks_run_in_a_private_clone_that_later_fetches_never_reach(worker):
    w, task = worker
    root = Path(task['root']).resolve()
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(dict(task, tenant='tenant-a', tenant_isolated=True))
    assert reports[-1]['type'] == 'succeeded'
    clone = w.state / 'worktrees' / 'task1-attempt1'
    common = subprocess.run(['git', '-C', str(clone), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                            check=True, capture_output=True, text=True).stdout.strip()
    assert Path(common).resolve() == (clone / '.git').resolve()
    # An object fetched into the root afterwards does not exist in the task's clone.
    blob = subprocess.run(['git', '-C', str(root), 'hash-object', '-w', '--stdin'], input=b'other tenant',
                          check=True, capture_output=True).stdout.decode().strip()
    assert subprocess.run(['git', '-C', str(clone), 'cat-file', '-e', blob], capture_output=True).returncode != 0
    assert not (root / '.git' / 'worktrees').exists()
    # The clone keeps no remote, and so no path back to the source repository.
    assert subprocess.run(['git', '-C', str(clone), 'remote'], check=True, capture_output=True, text=True).stdout == ''
    for path in (clone / '.git').rglob('*'):
        if path.is_file():
            assert str(root).encode() not in path.read_bytes(), path


def test_worker_refuses_tenant_roots_outside_its_allowlist(tmp_path, worker):
    w, _ = worker
    with pytest.raises(ValueError, match='tenant root'):
        Worker(dict(w.config, tenant_roots={str(tmp_path / 'elsewhere'): 'tenant-a'}))
    with pytest.raises(ValueError, match='tenant root'):
        Worker(dict(w.config, tenant_roots={w.config['allowed_roots'][0]: 'Not A Tenant'}))


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


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid, seconds=3):
    import time
    deadline = time.monotonic() + seconds
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not alive(pid)


BACKGROUND_LEADER = ('#!/usr/bin/env python3\nimport json,subprocess,sys\nsys.stdin.read()\n'
                     'p = subprocess.Popen(["sleep","60"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n'
                     'open(%r,"w").write(str(p.pid))\n'
                     'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"done"}}))\n')


def test_background_descendant_is_terminated_when_the_leader_exits_first(worker, tmp_path):
    w, task = worker
    pidfile = tmp_path / 'child.pid'
    Path(w.config['codex_path']).write_text(BACKGROUND_LEADER % str(pidfile))
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    child = int(pidfile.read_text())
    try:
        assert reports[-1]['type'] == 'succeeded'
        assert wait_dead(child), 'background child outlived its runtime leader'
    finally:
        if alive(child):
            os.kill(child, 9)


def test_stop_group_terminates_descendants_of_an_already_exited_leader(tmp_path):
    pidfile = tmp_path / 'child.pid'
    leader = subprocess.Popen([sys.executable, '-c', 'import subprocess; p = subprocess.Popen(["sleep","60"]); '
                               'open(%r,"w").write(str(p.pid))' % str(pidfile)], start_new_session=True)
    leader.wait(timeout=10)  # cancellation can arrive after the leader is gone
    child = int(pidfile.read_text())
    try:
        assert alive(child)
        stop_group(leader)
        assert wait_dead(child)
    finally:
        if alive(child):
            os.kill(child, 9)


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess,'check_output',lambda args,**kwargs:'' if 'status' in args else 'revision\n')
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
    assert kwargs['env']['CUSTOM_BASE_URL'] == bridge.config['gateway_url']
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


@pytest.fixture
def hermes_checkout(tmp_path):
    root = tmp_path / 'hermes'
    (root / 'hermes_cli').mkdir(parents=True)
    (root / 'hermes_cli' / '__init__.py').write_text('')
    (root / 'toolsets.py').write_text('')
    (root / '.gitignore').write_text('venv/\n*.pyc\n__pycache__/\nbuild/\ncache/\n')
    git = ['git', '-C', str(root), '-c', 'user.name=T', '-c', 'user.email=t@example.invalid']
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run([*git, 'add', '.'], check=True)
    subprocess.run([*git, 'commit', '-q', '-m', 'pinned'], check=True)
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    return root, revision


def test_hermes_pin_accepts_a_clean_checkout_with_harmless_ignored_files(hermes_checkout):
    root, revision = hermes_checkout
    (root / 'venv' / 'lib').mkdir(parents=True)
    (root / 'venv' / 'pyvenv.cfg').write_text('home = /usr/bin\n')
    (root / 'venv' / 'lib' / 'site.py').write_text('')
    (root / 'hermes_cli' / '__pycache__').mkdir()
    (root / 'hermes_cli' / '__pycache__' / 'main.cpython-314.pyc').write_bytes(b'')
    (root / 'cache').mkdir()
    (root / 'cache' / 'data.json').write_text('{}')
    verify_hermes_checkout(str(root), revision)
    with pytest.raises(ValueError, match='differs from approved pin'):
        verify_hermes_checkout(str(root), '0' * 40)


@pytest.mark.parametrize('mutate', [
    lambda root: (root / 'toolsets.py').write_text('import os; os.system("id")'),         # tracked edit
    lambda root: (root / 'json.py').write_text(''),                                     # untracked shadow module
    lambda root: (root / 'hermes_cli' / 'extra.py').write_text(''),                     # untracked in a package
    lambda root: (root / 'toolsets.pyc').write_bytes(b''),                              # ignored sourceless bytecode
    lambda root: ((root / 'build').mkdir(), (root / 'build' / '__init__.py').write_text('')),  # ignored package
])
def test_hermes_pin_refuses_a_dirty_checkout(hermes_checkout, mutate):
    root, revision = hermes_checkout
    mutate(root)
    with pytest.raises(ValueError, match='refusing to run unpinned code'):
        verify_hermes_checkout(str(root), revision)


def test_bridge_rechecks_the_checkout_before_every_run(hermes_checkout, tmp_path, monkeypatch):
    root, revision = hermes_checkout
    key = tmp_path / 'key'
    key.write_text('gateway-secret')
    key.chmod(0o600)
    bridge = Bridge(dict(token='bridge-secret', hermes_root=str(root), hermes_revision=revision,
                         hermes_python='/python', gateway_key_file=str(key), gateway_url='http://127.0.0.1:20128/v1'))
    ran = []
    real_run = subprocess.run
    def fake(command, **kwargs):
        if command[0] == 'git':
            return real_run(command, **kwargs)
        ran.append(kwargs['env'])
        return subprocess.CompletedProcess(command, 0, json.dumps({'type': 'result', 'exit_code': 0, 'text': json.dumps(
            {'summary': 'Ready', 'logical_role': 'interpreter'})}) + '\n', '')
    monkeypatch.setattr(subprocess, 'run', fake)
    body = dict(title='Review', brief='Original instruction', project='snowgloves')
    bridge.interpret(body)
    assert ran and ran[-1]['PYTHONPYCACHEPREFIX'] == bridge.pycache and str(root) not in bridge.pycache
    (root / 'toolsets.py').write_text('tampered = True\n')  # changed after the bridge started
    with pytest.raises(ValueError, match='refusing to run unpinned code'):
        bridge.interpret(body)
    assert len(ran) == 1


def _task_account(worker, tmp_path, monkeypatch, log_name='sudo.log'):
    """Point the worker at a stand-in sudo that records each call and runs the command as us,
    except pkill, which it only records (it must never signal this test's own processes)."""
    import fleet_worker
    import pwd as accounts
    w, task = worker
    me = accounts.getpwuid(os.getuid()).pw_name
    monkeypatch.setattr(fleet_worker, 'account_uid', lambda name: 99999)
    root = tmp_path / 'task-root'
    root.mkdir(mode=0o711)
    root.chmod(0o711)
    calls = tmp_path / log_name
    sudo = tmp_path / 'sudo'
    sudo.write_text('#!/usr/bin/env python3\n'
                    'import json, os, sys\n'
                    'args = sys.argv[1:]\n'
                    # Parse like sudo: options (-n, -u USER, --preserve-env=...), then an optional --.
                    'i = 0\n'
                    'while i < len(args) and args[i].startswith("-") and args[i] != "--":\n'
                    '    i += 2 if args[i] == "-u" else 1\n'
                    'rest = args[i + 1:] if i < len(args) and args[i] == "--" else args[i:]\n'
                    'with open(%r, "a") as log: log.write(json.dumps({"args": args, "env": sorted(os.environ)}) + "\\n")\n'
                    'if rest and rest[0] == "/usr/bin/pkill": sys.exit(0)\n'
                    # Never let a scrub touch anything outside this test's own folder.
                    'if rest and rest[0] == "/usr/bin/find" and not all(a.startswith(%r) for a in rest[1:rest.index("-xdev")]): sys.exit(2)\n'
                    'if rest and rest[0] == "/bin/rm" and os.path.exists(%r): sys.exit(1)\n'
                    # As macOS may: empty the home but refuse the folder itself, exiting nonzero.
                    'if rest and rest[0] == "/bin/rm" and os.path.exists(%r):\n'
                    '    import shutil\n'
                    '    for name in os.listdir(rest[-1]): shutil.rmtree(os.path.join(rest[-1], name))\n'
                    '    sys.exit(1)\n'
                    'os.execv(rest[0], rest)\n' % (str(calls), str(tmp_path), str(tmp_path / 'fail-rm'), str(tmp_path / 'keep-home-dir')))
    sudo.chmod(0o700)
    # A stand-in pgrep: "no processes" unless a flag file says the account is still busy.
    pgrep = tmp_path / 'pgrep'
    pgrep.write_text('#!/bin/sh\n[ -e %s ] && exit 0\nexit 1\n' % (tmp_path / 'busy'))
    pgrep.chmod(0o700)
    shared = tmp_path / 'shared-tmp'
    shared.mkdir()
    config = dict(w.config, task_users={'tenant-a': me}, task_root=str(root), sudo_path=str(sudo), pgrep_path=str(pgrep),
                  task_scrub_roots=[str(shared)], task_scrub_user_dir=False)
    return fleet_worker.Worker(config), dict(task, tenant='tenant-a', tenant_isolated=True), root, calls


def test_tenant_tasks_run_as_the_task_account_in_a_private_workdir(worker, tmp_path, monkeypatch):
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'succeeded'
    records = [json.loads(line) for line in calls.read_text().splitlines()]
    run = next(r for r in records if '--' in r['args'] and r['args'][r['args'].index('--') + 1].endswith('codex'))
    assert run['args'][:3] == ['-n', '-u', w.task_users['tenant-a']]
    preserved = run['args'][3].split('=', 1)[1].split(',')
    assert 'OMNIROUTE_API_KEY' in preserved and {'HOME', 'CODEX_HOME', 'TMPDIR'} <= set(preserved)
    # The key travels only in the environment, never on the command line.
    assert not any('gateway-secret' in arg for arg in run['args'])
    # The run used a workdir under task_root, never the worker's own state, and it was deleted
    # (not merely retained).
    assert '-C' in run['args'] and run['args'][run['args'].index('-C') + 1].startswith(str(root))
    assert list(root.iterdir()) == [] and not (w.state / 'worktrees').exists()
    assert not (w.state / 'retained-task-workdirs').exists() and not w.held.exists()
    assert any(r['args'][3:5] == ['/bin/rm', '-rf'] for r in records)


def test_task_account_runs_are_reaped_and_refuse_write(worker, tmp_path, monkeypatch):
    import fleet_worker
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(dict(task, access='write'))
    assert reports[-1]['type'] == 'failed'
    w.execute(dict(task, id='task2', attempt_id='attempt2'))
    records = [json.loads(line)['args'] for line in calls.read_text().splitlines()]
    # After the run, whatever the task account still runs is ended through sudo.
    assert any(args[-4:] == ['/usr/bin/pkill', '-KILL', '-U', w.task_users['tenant-a']] for args in records)


@pytest.mark.parametrize('change', ['same-account', 'no-root', 'group-writable-root', 'closed-root'])
def test_worker_refuses_an_unsafe_task_account_setup(worker, tmp_path, monkeypatch, change):
    import fleet_worker
    import pwd as accounts
    w, _ = worker
    root = tmp_path / 'task-root'
    root.mkdir()
    root.chmod({'group-writable-root': 0o771, 'closed-root': 0o700}.get(change, 0o711))
    monkeypatch.setattr(fleet_worker, 'account_uid', lambda name: os.getuid() if change == 'same-account' else 99999)
    config = dict(w.config, task_users={'tenant-a': accounts.getpwuid(os.getuid()).pw_name}, task_root=str(root))
    if change == 'no-root':
        config.pop('task_root')
    with pytest.raises(ValueError):
        fleet_worker.Worker(config)


def test_a_failed_task_account_run_is_kept_privately_for_reconciliation(worker, tmp_path, monkeypatch):
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    failing = tmp_path / 'codex-fails'
    failing.write_text('#!/bin/sh\ncat >/dev/null\nexit 3\n')
    failing.chmod(0o700)
    w.config['codex_path'] = str(failing)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'failed'
    kept = w.state / 'retained-task-workdirs' / 'task1-attempt1'
    # Moved out of task_root (shared with the task account) into the worker's own state.
    assert list(root.iterdir()) == [] and (kept / 'repo' / 'MANIFEST.yaml').exists() and not w.held.exists()


def test_cleanup_failure_after_success_keeps_the_workdir_or_holds_dispatch(worker, tmp_path, monkeypatch):
    import fleet_worker
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    (tmp_path / 'fail-rm').write_text('')
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'succeeded'
    # Removal failed, so the run was retained privately rather than left behind.
    assert list(root.iterdir()) == [] and (w.state / 'retained-task-workdirs' / 'task1-attempt1').exists()
    # If it can be neither removed nor moved, nothing more is dispatched.
    monkeypatch.setattr(fleet_worker.os, 'rename', lambda *a: (_ for _ in ()).throw(OSError('cross-device')))
    w.execute(dict(task, id='task2', attempt_id='attempt2'))
    assert (root / 'task2-attempt2').exists() and json.loads(w.held.read_text())['attempt_id'] == 'attempt2'


def test_restart_moves_leftover_task_workdirs_out_of_reach(worker, tmp_path, monkeypatch):
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    (root / 'old-attempt' / 'home').mkdir(parents=True)
    w.request = lambda route, body: {}
    w.recover()
    assert list(root.iterdir()) == [] and (w.state / 'retained-task-workdirs' / 'old-attempt' / 'home').exists()


def test_surviving_task_account_processes_hold_dispatch(worker, tmp_path, monkeypatch):
    import fleet_worker
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    monkeypatch.setattr(fleet_worker.time, 'sleep', lambda seconds: None)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    # Something keeps running as the task account after the run (pkill cannot end it).
    real_settle = w.settle_task_workdir
    def settle(workdir, task_, succeeded, user):
        (tmp_path / 'busy').write_text('')
        real_settle(workdir, task_, succeeded, user)
    w.settle_task_workdir = settle
    w.execute(task)
    assert json.loads(w.held.read_text())['reason'].startswith('Task-account processes survived')
    # And a run never starts while the account is busy.
    w.held.unlink()
    w.execute(dict(task, id='task2', attempt_id='attempt2'))
    assert reports[-1]['type'] == 'failed' and not (root / 'task2-attempt2').exists()
    assert 'not idle' in json.loads(w.held.read_text())['reason']


def test_cleanup_succeeds_when_only_the_empty_home_folder_is_refused(worker, tmp_path, monkeypatch):
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    (tmp_path / 'keep-home-dir').write_text('')
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'succeeded'
    # Deleted, not retained: the task account emptied its home and this account removed the rest.
    assert list(root.iterdir()) == [] and not (w.state / 'retained-task-workdirs').exists() and not w.held.exists()


def test_files_a_run_leaves_in_shared_temp_folders_are_scrubbed(worker, tmp_path, monkeypatch):
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    # Stands in for a run that copied tenant data to /tmp for a later run to read.
    real_settle = w.settle_task_workdir
    def settle(workdir, task_, succeeded, user):
        (tmp_path / 'shared-tmp' / 'stash').mkdir()
        (tmp_path / 'shared-tmp' / 'stash' / 'copy.md').write_text('tenant-a private context')
        real_settle(workdir, task_, succeeded, user)
    w.settle_task_workdir = settle
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'succeeded'
    assert list((tmp_path / 'shared-tmp').iterdir()) == [] and not w.held.exists()


def test_an_unconfirmable_scrub_holds_dispatch(worker, tmp_path, monkeypatch):
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    monkeypatch.setattr(w, 'scrub_task_account', lambda user: False)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(task)
    assert reports[-1]['type'] == 'failed' and 'clean' in json.loads(w.held.read_text())['reason']


def test_a_failing_scrub_command_fails_closed(worker, tmp_path, monkeypatch):
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    # Stands in for a host whose sudoers entry does not yet allow find.
    real_run = subprocess.run
    def run(argv, *args, **kwargs):
        if isinstance(argv, list) and '/usr/bin/find' in argv:
            return subprocess.CompletedProcess(argv, 1, b'', b'sudo: a password is required')
        return real_run(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    assert w.scrub_task_account(w.task_users['tenant-a']) is False


def test_worker_refuses_a_task_root_with_acl_entries(worker, tmp_path, monkeypatch):
    import fleet_worker
    import pwd as accounts
    w, _ = worker
    root = tmp_path / 'task-root'
    root.mkdir()
    root.chmod(0o711)
    subprocess.run(['/bin/chmod', '+a', 'everyone allow add_file,add_subdirectory,file_inherit,directory_inherit', str(root)], check=True)
    monkeypatch.setattr(fleet_worker, 'account_uid', lambda name: 99999)
    with pytest.raises(ValueError, match='ACL'):
        fleet_worker.Worker(dict(w.config, task_users={'tenant-a': accounts.getpwuid(os.getuid()).pw_name}, task_root=str(root)))


def test_restart_reaps_the_task_account_or_holds(worker, tmp_path, monkeypatch):
    import fleet_worker
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    monkeypatch.setattr(fleet_worker.time, 'sleep', lambda seconds: None)
    w.request = lambda route, body: {}
    w.recover()
    # Recovery checked the task account and found it idle, so nothing is held.
    assert not w.held.exists()
    (tmp_path / 'busy').write_text('')
    w.recover()
    assert 'restart' in json.loads(w.held.read_text())['reason']


def test_each_tenant_runs_as_its_own_account_and_an_unmapped_tenant_is_refused(worker, tmp_path, monkeypatch):
    import fleet_worker
    w, task, root, calls = _task_account(worker, tmp_path, monkeypatch)
    reports = []
    w.request = lambda route, body: reports.append(body) or {}
    w.execute(dict(task, tenant='tenant-b', id='task9', attempt_id='attempt9'))
    # No account for tenant-b: refused before any workdir or sudo call exists.
    assert reports[-1]['type'] == 'failed' and not (root / 'task9-attempt9').exists() and not calls.exists()


@pytest.mark.parametrize('mapping', [{'tenant-a': 'same', 'tenant-b': 'same'}, {}, ['tenant-a'], {'Tenant A': 'sg-a'}])
def test_worker_refuses_a_task_account_map_that_shares_or_is_malformed(worker, tmp_path, monkeypatch, mapping):
    import fleet_worker
    w, _ = worker
    root = tmp_path / 'task-root'
    root.mkdir()
    root.chmod(0o711)
    monkeypatch.setattr(fleet_worker, 'account_uid', lambda name: 99999)
    with pytest.raises(ValueError):
        fleet_worker.Worker(dict(w.config, task_users=mapping, task_root=str(root)))


def test_worker_refuses_the_retired_shared_task_user_setting(worker, tmp_path):
    import fleet_worker
    w, _ = worker
    with pytest.raises(ValueError, match='task_users'):
        fleet_worker.Worker(dict(w.config, task_user='sg-task', task_root=str(tmp_path)))

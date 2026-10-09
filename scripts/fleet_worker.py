#!/usr/bin/env python3
"""Single-slot pilot worker. Never retries execution after an uncertain outcome."""
import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from lib.fleet_coordinator import redact


DENY_DIRS = ('.git', '.github', '_runtime')
DENY_FILES = ('.env', '.env.*', '*.pem', '*.key', '*.p12', '*.pfx', 'id_rsa*', 'id_ed25519*', 'credentials*', '*.token', '*.secret')
SECRET_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r'\b(?:sk-|ghp_|gho_|github_pat_)[A-Za-z0-9_-]{8,}',
    r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}',
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    r'\bAKIA[0-9A-Z]{16}\b',
))


WRITE_PREAMBLE = ('You are in an isolated, disposable working tree. Edit files here only. Do not commit, push, use the network, '
                  'or touch credentials, .env files, .git or CI configuration. Make every edit yourself by running shell commands with your shell tool; '
                  'the apply_patch tool is unavailable here, and describing or suggesting a command without running it makes no change. '
                  'The operator reviews your diff and the worker runs the tests.\n\n')


EFFECT_ITEMS = ('command_execution', 'file_change', 'mcp_tool_call', 'web_search')
TRANSIENT = re.compile(r'\b429\b|Too Many Requests|stream (?:closed|disconnected)', re.I)


class WriteRejected(ValueError):
    """A write attempt failed a gate; the message is safe to report."""


def load_config(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Configuration must be a private regular file with mode 0600')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Invalid configuration')
    return value


def runtime_environment():
    return {name: os.environ[name] for name in
            ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
            if name in os.environ}


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def stop_group(process):
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


class Worker:
    def __init__(self, config):
        self.config = config
        self.state = Path(config['state_root']).resolve()
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.pending = self.state / 'pending.json'
        self.active = self.state / 'active.json'
        self.held = self.state / 'recovery-required.json'
        self.stopping = False
        self.gateway_key = None
        if not config['endpoint'].startswith('http://127.0.0.1:'):
            raise ValueError('Pilot coordinator must use loopback')
        if config.get('gateway_url') != 'http://127.0.0.1:20128/v1':
            raise ValueError('Pilot gateway must use the reviewed loopback route')

    def request(self, route, body):
        request = Request(self.config['endpoint'].rstrip('/') + route,
                          data=json.dumps(body).encode(), method='POST',
                          headers={'Authorization': 'Bearer ' + self.config['token'], 'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def report(self, task, kind, **fields):
        return dict(task_id=task['id'], attempt_id=task['attempt_id'],
                    lease_token=task['lease_token'], event_id=uuid.uuid4().hex, type=kind, **fields)

    def flush(self):
        if not self.pending.exists():
            return True
        body = json.loads(self.pending.read_text())
        try:
            self.request('/v1/worker/report', body)
        except HTTPError as error:
            if error.code in (403, 409):
                private_json(self.state / ('held-' + body['attempt_id'] + '.json'), body)
                private_json(self.held, {'attempt_id': body['attempt_id'], 'reason': 'Assignment rejected; reconcile before dispatch'})
                self.pending.unlink()
                if self.active.exists():
                    self.active.unlink()
                return True
            return False
        except (OSError, ValueError):
            return False
        self.pending.unlink()
        if self.active.exists():
            self.active.unlink()
        return True

    def recover(self):
        # Do not resume/replay a CLI after worker loss. Coordinator lease fencing
        # holds the old assignment if its terminal report can no longer be accepted.
        if self.active.exists() and not self.pending.exists():
            task = json.loads(self.active.read_text())
            private_json(self.held, {'attempt_id': task['attempt_id'], 'reason': 'Prior process state uncertain; reconcile before dispatch'})
            private_json(self.pending, self.report(task, 'interrupted', message='Worker restarted; manual reconciliation required'))
        return self.flush()

    def command(self, worktree, write=False):
        c = self.config
        return [c['codex_path'], 'exec', '--ignore-user-config', '--json', '--sandbox', 'workspace-write' if write else 'read-only',
                '--skip-git-repo-check', '-C', str(worktree), '-m', c.get('model', 'noesis-fast'),
                *(['-c', 'sandbox_workspace_write.network_access=false'] if write else []),
                '-c', 'model_provider="omniroute"', '-c', 'model_providers.omniroute.name="OmniRoute"',
                '-c', 'model_providers.omniroute.base_url=' + json.dumps(c['gateway_url']),
                '-c', 'model_providers.omniroute.env_key="OMNIROUTE_API_KEY"',
                '-c', 'model_providers.omniroute.wire_api="responses"', '-']

    def transient_before_effects(self, log):
        """True only when a failed run hit a transient provider error and provably did nothing yet:
        no command, edit, tool or web call started, so replaying cannot repeat a side effect."""
        transient = False
        for line in Path(log).read_text(errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (row.get('item') or {}).get('type') in EFFECT_ITEMS:
                return False
            message = row.get('message') or (row.get('error') or {}).get('message') or ''
            if row.get('type') in ('error', 'turn.failed') and TRANSIENT.search(str(message)):
                transient = True
        return transient

    def monitor(self, task, start, done, process=None):
        """Heartbeat, honour cancellation, the time budget and shutdown until done(). Returns (kind, message)
        when stopped early, else (None, None)."""
        last_heartbeat = 0
        while not done():
            if self.stopping:
                if process:
                    stop_group(process)
                return 'interrupted', 'Worker stopped; manual reconciliation required'
            now = time.monotonic()
            if now - start > self.config.get('job_timeout', 300):
                if process:
                    stop_group(process)
                return 'interrupted', 'Execution time budget exceeded; no automatic replay'
            if now - last_heartbeat >= min(10, self.config.get('heartbeat_seconds', 5)):
                last_heartbeat = now
                try:
                    response = self.request('/v1/worker/report', self.report(task, 'heartbeat'))
                    if response.get('cancel_requested'):
                        if process:
                            stop_group(process)
                        return 'cancelled', 'Cancellation completed'
                except HTTPError as error:
                    if error.code in (403, 409):
                        if process:
                            stop_group(process)
                        return 'interrupted', 'Assignment lost; manual reconciliation required'
                except (OSError, ValueError):
                    pass  # separate worker survives a brief coordinator restart
            time.sleep(0.2)
        return None, None

    def write_enabled(self, root):
        return (root in [Path(p).resolve() for p in self.config.get('write_roots', [])]
                and bool(self.config.get('test_commands', {}).get(str(root))))

    def keep_patch(self, task, text):
        path = self.state / 'patches' / (task['attempt_id'] + '.patch')
        path.parent.mkdir(exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)

    def verification_profile(self, worktree, scratch):
        """Seatbelt profile for proposed code: writes only in the worktree and a private scratch dir, no home
        reads, no network except loopback. An argv allowlist and a cwd do not confine what the argv executes."""
        home = os.path.realpath(os.path.expanduser('~'))
        denied = [os.path.realpath(p) for p in self.config.get('verify_deny_read', [home])]
        library = [os.path.realpath(p) for p in self.config.get('verify_python_paths', [])]
        paths = [str(worktree), str(scratch), *denied, *library]
        if any(c in p for p in paths for c in '"\\\n'):
            raise WriteRejected('Verification paths contain unsafe characters')
        return '\n'.join([
            '(version 1)', '(allow default)',
            '(deny network*)', '(allow network* (remote ip "localhost:*"))', '(allow network-bind network-inbound (local ip "localhost:*"))',
            '(deny file-write*)',
            '(allow file-write* (subpath "%s") (subpath "%s") (literal "/dev/null") (literal "/dev/dtracehelper") (literal "/dev/tty"))' % (worktree, scratch),
            *['(deny file-read* (subpath "%s"))' % p for p in denied],
            '(allow file-read-metadata)',
            '(allow file-read* (subpath "%s") (subpath "%s"))' % (worktree, scratch),
            *['(allow file-read* (subpath "%s"))' % p for p in library],  # read-only interpreter libraries, e.g. pytest
            '(deny signal)', '(allow signal (target same-sandbox) (target self))', ''])  # no killing the worker or its neighbours

    def sandboxed(self, task, worktree):
        """Return (argv prefix, scratch dir) that confines a verification command, or fail closed."""
        sandbox = self.config.get('sandbox_exec_path', '/usr/bin/sandbox-exec')
        if not os.access(sandbox, os.X_OK):
            raise WriteRejected('Verification sandbox is unavailable')
        scratch = self.state / 'verify-tmp' / task['attempt_id']
        scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = scratch.parent / (task['attempt_id'] + '.sb')
        fd = os.open(profile, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(self.verification_profile(Path(worktree).resolve(), scratch.resolve()))
        prefix = [sandbox, '-f', str(profile)]
        probe = subprocess.run([*prefix, '/usr/bin/true'], capture_output=True, timeout=15)
        if probe.returncode:
            raise WriteRejected('Verification sandbox is unavailable')
        return prefix, scratch

    def collect_write(self, task, root, worktree):
        """Compute the patch ourselves (never trust the agent), gate it, then run the allowlisted tests."""
        git = self.config.get('git_path', 'git')
        def run_git(*args):
            return subprocess.run([git, '-C', str(worktree), *args], check=True, capture_output=True, timeout=60).stdout
        def snapshot():
            run_git('add', '-A')
            names = sorted(n for n in run_git('diff', '--cached', '--name-only', '-z', '--no-renames').decode('utf-8', 'replace').split('\0') if n)
            return names, run_git('diff', '--cached', '--binary', '--no-color', '--no-renames')
        names, raw = snapshot()
        if not names:
            raise WriteRejected('No changes were produced')
        for name in names:
            parts = name.split('/')
            if any(part in DENY_DIRS for part in parts) or any(fnmatch.fnmatch(parts[-1], pattern) for pattern in DENY_FILES):
                raise WriteRejected('Patch touches a denied path')
        summary = run_git('diff', '--cached', '--summary', '--no-renames').decode('utf-8', 'replace')
        if 'mode 120000' in summary or 'mode 160000' in summary:
            raise WriteRejected('Patch adds a symlink or submodule')
        if len(raw) > self.config.get('max_patch_bytes', 1048576):
            raise WriteRejected('Patch is too large')
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            raise WriteRejected('Patch is not valid UTF-8 text') from None
        if any(p.search(text) for p in SECRET_PATTERNS) or any(v and v in text for v in (self.config.get('token'), self.gateway_key)):
            raise WriteRejected('Patch contains credential-like content')
        sandbox, scratch = self.sandboxed(task, worktree)
        env = runtime_environment()
        env.update(PYTHONDONTWRITEBYTECODE='1', HOME=str(scratch), TMPDIR=str(scratch))  # nothing from the real home or temp
        if self.config.get('verify_python_paths'):
            env['PYTHONPATH'] = os.pathsep.join(self.config['verify_python_paths'])
        results = []
        for command in self.config['test_commands'][str(root)]:
            argv = command['argv']
            cwd = (worktree / command.get('cwd', '.')).resolve()
            if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv) or not cwd.is_relative_to(worktree.resolve()):
                raise WriteRejected('Invalid test command configuration')
            try:
                done = subprocess.run([*sandbox, *argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=command.get('timeout', 600))
            except subprocess.TimeoutExpired:
                self.keep_patch(task, text)
                raise WriteRejected('Test command timed out') from None
            tail = redact((done.stdout + done.stderr).decode('utf-8', 'replace')[-2000:]).strip()
            results.append({'argv': argv, 'exit_code': done.returncode, 'tail': tail})
            if done.returncode:
                self.keep_patch(task, text)
                raise WriteRejected('Tests failed (exit %d): %s' % (done.returncode, os.path.basename(argv[0])))
        if snapshot()[1] != raw:
            self.keep_patch(task, text)
            raise WriteRejected('Tests modified the working tree')
        return dict(access='write', base=run_git('rev-parse', 'HEAD').decode().strip(), files=names,
                    patch={'text': text, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}, tests=results)

    def execute(self, task):
        private_json(self.active, task)
        kind, message, artifact = 'failed', 'Execution did not complete', None
        process = None
        try:
            for key in ('id', 'attempt_id'):
                if not re.fullmatch('[a-zA-Z0-9_-]{1,100}', task[key]):
                    raise ValueError('Invalid assignment identifier')
            root = Path(task['root']).resolve()
            if root not in [Path(p).resolve() for p in self.config['allowed_roots']] or task['runtime'] != 'codex':
                raise ValueError('Unsupported assignment')
            write = task.get('access') == 'write'
            if write and not self.write_enabled(root):
                raise WriteRejected('Write is not enabled for this worker and project')
            artifact_root = Path(task['artifacts_root']).resolve()
            if artifact_root != Path(self.config['artifacts_root']).resolve():
                raise ValueError('Unapproved artifact root')
            key_path = Path(self.config['gateway_key_file'])
            if key_path.stat().st_mode & 0o077:
                raise ValueError('Gateway key must have mode 0600')
            key = key_path.read_text().strip()
            if not key:
                raise ValueError('Gateway credential unavailable')
            self.gateway_key = key
            worktree = self.state / 'worktrees' / (task['id'] + '-' + task['attempt_id'])
            worktree.parent.mkdir(exist_ok=True, mode=0o700)
            subprocess.run([self.config.get('git_path', 'git'), '-C', str(root), 'worktree', 'add', '--detach', str(worktree), 'HEAD'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            env = runtime_environment()
            env['OMNIROUTE_API_KEY'] = key
            start = time.monotonic()
            runs = 1 + max(0, int(self.config.get('transient_retries', 2)))
            for run in range(runs):
                log = self.state / (task['attempt_id'] + ('.retry%d' % run if run else '') + '.jsonl')
                with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
                    process = subprocess.Popen(self.command(worktree, write), stdin=subprocess.PIPE, stdout=output, stderr=output,
                                               env=env, start_new_session=True)
                    process.stdin.write(((WRITE_PREAMBLE if write else '') + task['brief']).encode())
                    process.stdin.close()
                    early, note = self.monitor(task, start, lambda: process.poll() is not None, process)
                if early:
                    kind, message = early, note
                    break
                if process.returncode == 0 or run + 1 == runs or not self.transient_before_effects(log):
                    break
                # certain outcome: a transient provider error before anything ran, so a fresh run is safe
                deadline = time.monotonic() + self.config.get('transient_backoff', 20) * (run + 1)
                early, note = self.monitor(task, start, lambda: time.monotonic() >= deadline)
                if early:
                    kind, message = early, note
                    break
            if process.returncode == 0 and kind not in ('cancelled', 'interrupted'):
                finals = []
                for line in log.read_text(errors='replace').splitlines():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    item = row.get('item', {})
                    if row.get('type') == 'item.completed' and item.get('type') == 'agent_message':
                        finals.append(item.get('text', ''))
                if not finals or not finals[-1].strip():
                    raise ValueError('Runtime produced no final result')
                result = redact(finals[-1]).replace(key, '[REDACTED]').replace(self.config['token'], '[REDACTED]')
                artifact_path = artifact_root / (task['id'] + '-' + task['attempt_id'] + '.json')
                payload = dict(task_id=task['id'], attempt_id=task['attempt_id'], node=self.config['node_id'],
                               runtime='codex', model=self.config.get('model', 'noesis-fast'), output=result)
                if write:
                    payload.update(self.collect_write(task, root, worktree))
                private_json(artifact_path, payload)
                artifact = {'path': str(artifact_path), 'sha256': hashlib.sha256(artifact_path.read_bytes()).hexdigest()}
                kind, message = 'succeeded', 'Verified result artifact available'
            elif kind == 'failed':
                message = 'Runtime exited unsuccessfully; no automatic replay'
        except WriteRejected as error:
            message = str(error)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            if process:
                stop_group(process)
            message = 'Execution prerequisite or runtime failed; inspect private worker state'
        body = self.report(task, kind, message=message)
        if artifact:
            body['artifact'] = artifact
        private_json(self.pending, body)
        self.flush()

    def run(self):
        lock = os.open(self.state / 'worker.lock', os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.recover()
        while not self.stopping:
            if self.flush() and not self.held.exists():
                try:
                    task = self.request('/v1/worker/claim', {}).get('task')
                    if task:
                        self.execute(task)
                except (OSError, ValueError):
                    pass
            time.sleep(self.config.get('poll_seconds', 2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    worker = Worker(load_config(parser.parse_args().config))
    def shutdown(signum, frame):
        worker.stopping = True
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    worker.run()

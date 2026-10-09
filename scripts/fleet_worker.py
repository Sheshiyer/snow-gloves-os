#!/usr/bin/env python3
"""Single-slot pilot worker. Never retries execution after an uncertain outcome."""
import argparse
import fcntl
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

    def command(self, worktree):
        c = self.config
        return [c['codex_path'], 'exec', '--ignore-user-config', '--json', '--sandbox', 'read-only',
                '--skip-git-repo-check', '-C', str(worktree), '-m', c.get('model', 'noesis-fast'),
                '-c', 'model_provider="omniroute"', '-c', 'model_providers.omniroute.name="OmniRoute"',
                '-c', 'model_providers.omniroute.base_url=' + json.dumps(c['gateway_url']),
                '-c', 'model_providers.omniroute.env_key="OMNIROUTE_API_KEY"',
                '-c', 'model_providers.omniroute.wire_api="responses"', '-']

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
            artifact_root = Path(task['artifacts_root']).resolve()
            if artifact_root != Path(self.config['artifacts_root']).resolve():
                raise ValueError('Unapproved artifact root')
            key_path = Path(self.config['gateway_key_file'])
            if key_path.stat().st_mode & 0o077:
                raise ValueError('Gateway key must have mode 0600')
            key = key_path.read_text().strip()
            if not key:
                raise ValueError('Gateway credential unavailable')
            worktree = self.state / 'worktrees' / (task['id'] + '-' + task['attempt_id'])
            worktree.parent.mkdir(exist_ok=True, mode=0o700)
            subprocess.run([self.config.get('git_path', 'git'), '-C', str(root), 'worktree', 'add', '--detach', str(worktree), 'HEAD'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            log = self.state / (task['attempt_id'] + '.jsonl')
            env = runtime_environment()
            env['OMNIROUTE_API_KEY'] = key
            with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
                process = subprocess.Popen(self.command(worktree), stdin=subprocess.PIPE, stdout=output, stderr=output,
                                           env=env, start_new_session=True)
                process.stdin.write(task['brief'].encode())
                process.stdin.close()
                start, last_heartbeat = time.monotonic(), 0
                while process.poll() is None:
                    if self.stopping:
                        stop_group(process)
                        kind, message = 'interrupted', 'Worker stopped; manual reconciliation required'
                        break
                    now = time.monotonic()
                    if now - start > self.config.get('job_timeout', 300):
                        stop_group(process)
                        kind, message = 'interrupted', 'Execution time budget exceeded; no automatic replay'
                        break
                    if now - last_heartbeat >= min(10, self.config.get('heartbeat_seconds', 5)):
                        last_heartbeat = now
                        try:
                            response = self.request('/v1/worker/report', self.report(task, 'heartbeat'))
                            if response.get('cancel_requested'):
                                stop_group(process)
                                kind, message = 'cancelled', 'Cancellation completed'
                                break
                        except HTTPError as error:
                            if error.code in (403, 409):
                                stop_group(process)
                                kind, message = 'interrupted', 'Assignment lost; manual reconciliation required'
                                break
                        except (OSError, ValueError):
                            pass  # separate worker survives a brief coordinator restart
                    time.sleep(0.2)
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
                private_json(artifact_path, dict(task_id=task['id'], attempt_id=task['attempt_id'], node=self.config['node_id'],
                                               runtime='codex', model=self.config.get('model', 'noesis-fast'), output=result))
                artifact = {'path': str(artifact_path), 'sha256': hashlib.sha256(artifact_path.read_bytes()).hexdigest()}
                kind, message = 'succeeded', 'Verified result artifact available'
            elif kind == 'failed':
                message = 'Runtime exited unsuccessfully; no automatic replay'
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

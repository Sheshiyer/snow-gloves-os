#!/usr/bin/env python3
"""Digest-bound LaunchAgent -> LaunchDaemon migration; stdlib, no secret output.

Never handles FileVault, passwords, automatic login, provider setup or GUI apps.
See docs/fleet/HEADLESS-STARTUP.md. Apply/rollback are explicit root operations.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import pwd
import re
import shlex
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

SCHEMA = 'snowgloves.headless.v1'
DAEMONS = Path('/Library/LaunchDaemons')
BACKUPS = Path('/private/var/db/snowgloves-headless')
USERS = {'axio', 'maccoding2'}
SERVICES = {
    'axio': {'com.snowgloves.hermes-pilot.' + s for s in
             ('coordinator', 'bridge', 'worker', 'ui', 'api', 'tls', 'tls-renew', 'mcp-http')} |
            {'com.temperance.engine.omniroute', 'com.snowgloves.hermes'},
    'maccoding2': {'fr.heyzack.snowgloves.coding02-worker',
                   'fr.heyzack.snowgloves.coding02-transport'},
}
SSH_HOSTS = {'axio@coding-mac.tail32e298.ts.net', 'axio@100.117.187.123'}
KEYS = {'Label', 'Program', 'ProgramArguments', 'EnvironmentVariables',
        'WorkingDirectory', 'StandardOutPath', 'StandardErrorPath', 'RunAtLoad',
        'KeepAlive', 'ThrottleInterval', 'StartInterval', 'StartCalendarInterval',
        'ProcessType', 'ExitTimeOut', 'Nice', 'Umask'}
SECRET_KEY = re.compile(r'(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)', re.I)
SECRET_VALUE = re.compile(r'BEGIN [A-Z ]*PRIVATE' + r' KEY|\bsk-[A-Za-z0-9_-]{12,}|\beyJ[A-Za-z0-9_-]{12,}\.', re.I)
GUI = re.compile(r"""(?:^|/|["'])[^\n"']*\.app(?:/|["']|$)|osascript|(?:^|\n)\s*(?:exec\s+)?(?:/usr/bin/)?open(?:\s|$)|find-generic-password|find-internet-password|SSH_AUTH_SOCK""", re.I)


class Refused(ValueError):
    """Only fixed, non-sensitive reasons may be exposed to stdout/stderr."""


def require(ok, reason):
    if not ok:
        raise Refused(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def path_checked(value, within=None):
    require(isinstance(value, str) and value.startswith('/') and '\x00' not in value,
            'An absolute normalized path is required')
    p = Path(value)
    require(str(p) == value and '..' not in p.parts and '.' not in p.parts,
            'Noncanonical path refused')
    if within:
        require(p.is_relative_to(within) and p != within, 'Path is outside the service home')
    for component in [p, *p.parents]:
        require(not component.is_symlink(), 'Symlink path refused')
    return p


def private_file(path, uid, *, missing=False):
    if missing and not path.exists():
        return
    require(path.is_file(), 'Expected a regular private file')
    s = path.stat()
    require(s.st_uid == uid and stat.S_IMODE(s.st_mode) & 0o077 == 0,
            'Private file ownership or permissions are unsafe')


def fingerprint(path):
    s = path.stat()
    return {'path': str(path), 'sha256': digest(path.read_bytes()),
            'uid': s.st_uid, 'gid': s.st_gid, 'mode': stat.S_IMODE(s.st_mode)}


def user_info(user):
    require(user in USERS, 'Only the reviewed Coding Mac service users are supported')
    entry = pwd.getpwnam(user)
    require(entry.pw_uid > 0 and entry.pw_dir == '/Users/' + user,
            'Service user must be non-root with its expected home')
    return {'name': user, 'uid': entry.pw_uid, 'gid': entry.pw_gid, 'home': entry.pw_dir}


def safe_text(value):
    require(isinstance(value, str) and '\x00' not in value and '\n' not in value and '\r' not in value,
            'Invalid service string')
    require(not SECRET_VALUE.search(value), 'Inline credential material refused; use a private file')
    require(not GUI.search(value), 'GUI or interactive credential dependency refused')
    require(not re.search(r'https?://[^/\s]+@|[?&](?:token|key|password|secret)=', value, re.I),
            'Credential-bearing URL refused')
    require(not re.search(r'(?:authorization\s*[:=]|\bBearer\s+\S+|(?:token|password|secret|api[_-]?key)\s*=)', value, re.I),
            'Inline credential string refused')


def private_parent(path, info):
    p = path_checked(str(path.parent), Path(info['home']))
    require(p.is_dir(), 'Private directory must already exist')
    s = p.stat()
    require(s.st_uid == info['uid'] and stat.S_IMODE(s.st_mode) & 0o077 == 0,
            'Directory must be private and owned by the service user')
    private_file(path, info['uid'], missing=True)


def executable_path(value, home):
    # Homebrew normally uses symlinks; resolve only executable aliases inside its
    # reviewed tree and emit the resolved absolute binary in the system plist.
    p = Path(value)
    if p.is_relative_to(Path('/opt/homebrew')):
        p = p.resolve(strict=True)
        require(p.is_relative_to(Path('/opt/homebrew')), 'Executable alias escapes Homebrew')
        return path_checked(str(p))
    return path_checked(value)


def render(source, info):
    """Return generated plist and fingerprints; config content is never exposed."""
    home = Path(info['home'])
    source = path_checked(str(source), home)
    require(source.parent == home / 'Library/LaunchAgents', 'Source is not a user LaunchAgent')
    private_file(source, info['uid'])
    try:
        raw = plistlib.loads(source.read_bytes())
    except Exception:
        raise Refused('Invalid source plist') from None
    require(isinstance(raw, dict), 'Invalid source plist dictionary')
    label = raw.get('Label')
    require(label in SERVICES[info['name']] and source.name == label + '.plist',
            'Service label is outside the reviewed allowlist')
    require(set(raw) <= KEYS, 'Unreviewed or GUI-only launchd property refused')
    args = raw.get('ProgramArguments')
    require(isinstance(args, list) and args and all(isinstance(a, str) for a in args),
            'Explicit ProgramArguments are required')
    for arg in args:
        safe_text(arg)
    require(not any(re.match(r'--?(?:api[-_]?key|token|password|secret)(?:=|$)', a, re.I)
                    for a in args), 'Inline credential argument refused')
    require(raw.get('Program', args[0]) == args[0], 'Program and argv executable must agree')
    exe = executable_path(args[0], home)
    require(exe.is_file() and os.access(exe, os.X_OK), 'Executable is missing or not executable')
    require(exe.name not in {'open', 'osascript', 'security'}, 'GUI or Keychain executable refused')
    require(exe.is_relative_to(home) or any(exe.is_relative_to(Path(p)) for p in
            ('/usr/bin', '/bin', '/usr/sbin', '/opt/homebrew')), 'Executable root is unreviewed')
    if exe.name in {'bash', 'sh', 'zsh', 'env'}:
        require(exe.name != 'env' and len(args) >= 2 and args[1].startswith('/') and
                not any(a in {'-c', '-lc', '-l', '--login'} for a in args),
                'Inline or login shell refused; use an absolute wrapper file')
    files = [fingerprint(source), fingerprint(exe)]
    file_flags = {'--config', '--token-file', '--key-file', '--gateway-key-file'}
    for index, original_arg in enumerate(args[1:], 1):
        flag, equals, value = original_arg.partition('=')
        arg = value if equals and flag in file_flags else original_arg
        if arg.startswith('/'):
            require(Path(arg).exists(), 'Absolute service input is missing; explicit review required')
            p = path_checked(arg)
            require(p.is_relative_to(home) or p.is_relative_to(Path('/opt/homebrew')),
                    'Service input file is outside reviewed roots')
            if not p.is_file():
                require(p.is_dir(), 'Service input is not a regular path')
                continue
            if args[index - 1] in file_flags or equals and flag in file_flags:
                private_file(p, info['uid'])
            files.append(fingerprint(p))
            if p.suffix in {'.sh', '.py', '.js', '.mjs'}:
                require(not GUI.search(p.read_text(errors='replace')),
                        'Wrapper has a GUI or interactive credential dependency')
    env = raw.get('EnvironmentVariables', {})
    require(isinstance(env, dict), 'Invalid environment')
    env = dict(env)
    for k, v in env.items():
        require(isinstance(k, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k), 'Invalid environment name')
        safe_text(v)
        require(not SECRET_KEY.search(k) or k.endswith(('_FILE', '_PATH')),
                'Inline secret environment refused; use private files')
        if k.endswith(('_FILE', '_PATH')) and SECRET_KEY.search(k):
            p = path_checked(v, home)
            private_file(p, info['uid'])
            files.append(fingerprint(p))
    for k in ('HOME', 'USER', 'LOGNAME'):
        expected = info['home'] if k == 'HOME' else info['name']
        require(k not in env or env[k] == expected, 'Environment selects a different service user')
        env[k] = expected
    env.setdefault('PATH', '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin')
    require(all(p.startswith('/') and '..' not in Path(p).parts for p in env['PATH'].split(':')),
            'PATH must contain only absolute directories')
    # PATH directories may be symlinks in the macOS system layout; their resolved
    # targets must remain within standard system or selected service-user roots.
    for component in env['PATH'].split(':'):
        p = Path(component)
        require(str(p) == component and any(p.resolve().is_relative_to(Path(r)) for r in
                ('/opt/homebrew', '/usr', '/bin', '/sbin', info['home'])), 'Unreviewed PATH root')
    wd = path_checked(raw.get('WorkingDirectory', info['home']))
    require(wd.is_dir() and (wd == home or wd.is_relative_to(home)), 'Working directory is outside the service home')
    require('StandardOutPath' in raw and 'StandardErrorPath' in raw, 'Private stdout and stderr paths are required')
    for k in ('StandardOutPath', 'StandardErrorPath'):
        safe_text(raw[k])
        private_parent(path_checked(raw[k], home), info)
    for k in ('RunAtLoad', 'KeepAlive'):
        require(k not in raw or isinstance(raw[k], bool), 'Complex launch conditions need separate review')
    require('ProcessType' not in raw or raw['ProcessType'] == 'Background', 'GUI process type refused')
    for k in ('StartInterval', 'ThrottleInterval', 'ExitTimeOut'):
        require(k not in raw or type(raw[k]) is int and raw[k] > 0, 'Invalid launchd interval')
    if 'StartCalendarInterval' in raw:
        schedules = raw['StartCalendarInterval']
        schedules = schedules if isinstance(schedules, list) else [schedules]
        limits = {'Minute': (0, 59), 'Hour': (0, 23), 'Day': (1, 31), 'Weekday': (0, 7), 'Month': (1, 12)}
        require(bool(schedules), 'Empty schedule refused')
        for schedule in schedules:
            require(isinstance(schedule, dict) and bool(schedule) and set(schedule) <= set(limits), 'Invalid calendar schedule')
            require(all(type(v) is int and limits[k][0] <= v <= limits[k][1] for k, v in schedule.items()), 'Invalid calendar value')
    scheduled = 'StartInterval' in raw or 'StartCalendarInterval' in raw
    require(not scheduled or not raw.get('KeepAlive', False), 'Scheduled service must not run continuously')
    generated = dict(raw)
    generated['ProgramArguments'] = [str(exe), *args[1:]]
    with exe.open('rb') as binary:
        shebang = binary.read(512).split(b'\n', 1)[0].strip()
    if shebang.startswith(b'#!/usr/bin/env'):
        require(shebang == b'#!/usr/bin/env node', 'Environment-dependent shebang needs an explicit interpreter')
        node = executable_path('/opt/homebrew/bin/node', home)
        require(node.is_file() and os.access(node, os.X_OK), 'Explicit Node interpreter is unavailable')
        files.append(fingerprint(node))
        generated['ProgramArguments'] = [str(node), str(exe), *args[1:]]
    if 'Program' in generated:
        generated['Program'] = generated['ProgramArguments'][0]
    generated.update(UserName=info['name'], GroupName=grp.getgrgid(info['gid']).gr_name,
                     EnvironmentVariables=env, WorkingDirectory=str(wd), ProcessType='Background', Umask=0o077)
    generated['ThrottleInterval'] = max(30, min(300, raw.get('ThrottleInterval', 30)))
    generated.setdefault('RunAtLoad', not scheduled)
    if not scheduled:
        generated.setdefault('KeepAlive', True)
    return generated, {f['path']: f for f in files}


def run(command, *, info=None, check=True, timeout=25):
    def demote():
        os.initgroups(info['name'], info['gid'])
        os.setgid(info['gid'])
        os.setuid(info['uid'])
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C'}
    if info:
        env.update(HOME=info['home'], USER=info['name'], LOGNAME=info['name'])
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, env=env,
                                preexec_fn=demote if info and os.geteuid() == 0 else None)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused('Service command failed or timed out; inspect private host logs') from None
    require(not check or result.returncode == 0, 'Service command failed; inspect private host logs')
    return result


def loaded(domain, label):
    return run(['/bin/launchctl', 'print', domain + '/' + label], check=False).returncode == 0


def disabled(domain, label):
    result = run(['/bin/launchctl', 'print-disabled', domain], check=False)
    if result.returncode:
        require(not loaded(domain, label), 'Cannot inspect loaded service disable state')
        return False
    match = re.search(r'"' + re.escape(label) + r'"\s*=>\s*(\S+)', result.stdout.decode(errors='replace'))
    require(not match or match[1] in {'true', 'false', 'enabled', 'disabled'},
            'Unrecognized service disable state')
    return bool(match and match[1] in {'true', 'disabled'})


def stop_service(domain, label):
    # These reviewed Coding Macs support --wait. Without it bootout can return
    # while launchd still exposes the service, causing a false cutover failure.
    # run() bounds the documented potentially indefinite wait to 25 seconds.
    run(['/bin/launchctl', 'bootout', '--wait', domain + '/' + label], timeout=25)
    require(not loaded(domain, label), 'Service remains loaded after bounded stop')


DB_PROBE = """import hashlib,json,pathlib,sqlite3,sys,os,subprocess
p=pathlib.Path(sys.argv[1]); c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5)
r=c.execute('SELECT id,status,updated,worker,attempt_id,lease_hash,deadline FROM tasks ORDER BY id').fetchall()
s=c.execute('PRAGMA integrity_check').fetchone()[0]
live=any(subprocess.run(['/bin/launchctl','print',d+'/com.snowgloves.hermes-pilot.coordinator'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0 for d in ('system','gui/'+str(os.getuid()),'user/'+str(os.getuid())))
print(json.dumps({'ok':s=='ok','pending':sum(x[1] in ('queued','running','cancel_requested') for x in r),'state_sha256':hashlib.sha256(json.dumps(r,separators=(',',':')).encode()).hexdigest(),'scheduler_loaded':live}))
"""


def database_state(spec, info, *, require_stopped=False):
    db = path_checked(spec['db'], Path('/Users/axio'))
    if spec.get('ssh_host'):
        require(spec['ssh_host'] in SSH_HOSTS, 'Unreviewed coordinator SSH destination')
        identity = path_checked(spec.get('identity_file'), Path(info['home']))
        private_file(identity, info['uid'])
        command = ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                   '-o', 'StrictHostKeyChecking=yes', '-o', 'ForwardAgent=no', '-o', 'IdentityAgent=none',
                   '-o', 'IdentitiesOnly=yes', '-i', str(identity),
                   spec['ssh_host'], '/usr/bin/python3 -c ' + shlex.quote(DB_PROBE) + ' ' + shlex.quote(str(db))]
        result = run(command, info=info)
        try:
            state = json.loads(result.stdout)
        except Exception:
            raise Refused('Coordinator quiescence probe returned invalid data') from None
        require(not require_stopped or state.get('scheduler_loaded') is False,
                'Stop the coordinator before the Coding02 cutover or rollback')
        state.pop('scheduler_loaded', None)
    else:
        require(info['name'] == 'axio', 'Coding02 requires the coordinator SSH quiescence probe')
        private_file(db, info['uid'])
        try:
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
                rows = conn.execute('SELECT id,status,updated,worker,attempt_id,lease_hash,deadline FROM tasks ORDER BY id').fetchall()
                integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
            state = {'ok': integrity == 'ok', 'pending': sum(r[1] in ('queued', 'running', 'cancel_requested') for r in rows),
                     'state_sha256': digest(json.dumps(rows, separators=(',', ':')).encode())}
        except sqlite3.Error:
            raise Refused('Coordinator database probe failed') from None
    require(isinstance(state, dict) and state.get('ok') is True and type(state.get('pending')) is int and
            re.fullmatch('[0-9a-f]{64}', str(state.get('state_sha256', ''))), 'Invalid coordinator database evidence')
    require(state['pending'] == 0, 'Managed tasks are pending; cutover is not quiescent')
    return state


def filevault():
    result = run(['/usr/bin/fdesetup', 'status'], check=False)
    return 'off' if result.returncode == 0 and result.stdout.strip() == b'FileVault is Off.' else 'on-or-unknown'


def make_plan(user, labels, db, ssh_host=None, critical_files=(), identity_file=None):
    require(platform.system() == 'Darwin', 'This command requires the target macOS host')
    info = user_info(user)
    require(os.geteuid() in (0, info['uid']), 'Run inspect/plan as the selected service user or root')
    require(labels and len(labels) == len(set(labels)) and set(labels) <= SERVICES[user], 'Select unique reviewed labels explicitly')
    require(user != 'axio' or 'com.snowgloves.hermes-pilot.coordinator' in labels,
            'Coding01 migration must include its coordinator to fence submissions')
    require(user != 'axio' or not ssh_host, 'Coding01 must inspect its local authoritative database')
    spec = {'db': str(path_checked(db, Path('/Users/axio'))), 'ssh_host': ssh_host, 'identity_file': identity_file}
    state = database_state(spec, info)
    services, files = [], {}
    for label in labels:
        source = Path(info['home']) / 'Library/LaunchAgents' / (label + '.plist')
        generated, fingerprints = render(source, info)
        destination = DAEMONS / (label + '.plist')
        path_checked(str(destination))
        require(not destination.exists(), 'Destination already exists; migration refuses replacement')
        require(not loaded('system', label), 'Service already loaded in system domain')
        require(not disabled('system', label), 'System service is disabled; review its state separately')
        domains = ['gui/' + str(info['uid']), 'user/' + str(info['uid'])]
        domain_states = [{'domain': d, 'loaded': loaded(d, label), 'disabled': disabled(d, label)} for d in domains]
        require(sum(x['loaded'] for x in domain_states) <= 1, 'Duplicate user-domain service is already running')
        services.append({'label': label, 'source': str(source), 'destination': str(destination),
                         'plist': generated, 'domains': domain_states})
        files.update(fingerprints)
    for value in critical_files:
        p = path_checked(value, Path(info['home']))
        private_file(p, info['uid'])
        files[str(p)] = fingerprint(p)
    if ssh_host:
        p = path_checked(identity_file, Path(info['home']))
        private_file(p, info['uid'])
        files[str(p)] = fingerprint(p)
    body = {'schema': SCHEMA, 'host': platform.node(), 'user': info, 'created': int(time.time()),
            'quiescence': spec, 'database': state, 'filevault': filevault(),
            'services': services, 'files': files}
    return dict(body, sha256=digest(canonical(body)))


def validate_plan(plan, expected):
    require(isinstance(plan, dict) and plan.get('schema') == SCHEMA, 'Invalid plan schema')
    body = {k: v for k, v in plan.items() if k != 'sha256'}
    require(re.fullmatch('[0-9a-f]{64}', expected or '') and plan.get('sha256') == expected == digest(canonical(body)),
            'Reviewed plan digest does not match')
    require(plan.get('host') == platform.node(), 'Plan belongs to another host')
    info = user_info(plan['user']['name'])
    require(info == plan['user'], 'Service account changed since review')
    labels = [s['label'] for s in plan['services']]
    require(labels and len(labels) == len(set(labels)) and set(labels) <= SERVICES[info['name']], 'Invalid selected services')
    require(info['name'] != 'axio' or 'com.snowgloves.hermes-pilot.coordinator' in labels,
            'Coding01 migration must include its coordinator')
    for s in plan['services']:
        require(s['source'] == str(Path(info['home']) / 'Library/LaunchAgents' / (s['label'] + '.plist')) and
                s['destination'] == str(DAEMONS / (s['label'] + '.plist')), 'Invalid migration paths')
        require([d['domain'] for d in s['domains']] == ['gui/' + str(info['uid']), 'user/' + str(info['uid'])], 'Invalid launchd domain')
    return info


def write_private(path, data, *, mode=0o600, uid=0, gid=0):
    path_checked(str(path))
    require(path.parent.is_dir(), 'Destination parent missing')
    fd, name = tempfile.mkstemp(prefix='.headless-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        if os.geteuid() == 0:
            os.fchown(fd, uid, gid)
        else:
            require(uid == os.geteuid(), 'Cannot write for another account')
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def require_root():
    require(platform.system() == 'Darwin' and os.geteuid() == 0, 'Apply/rollback requires explicit root execution on macOS')
    for path in (DAEMONS, BACKUPS.parent):
        path_checked(str(path))
        require(path.is_dir() and path.stat().st_uid == 0 and stat.S_IMODE(path.stat().st_mode) & 0o022 == 0,
                'System destination ownership or permissions are unsafe')


def root_private_directory(path):
    require(path.is_dir() and path.stat().st_uid == 0 and stat.S_IMODE(path.stat().st_mode) == 0o700,
            'Backup directory must be root-owned mode 0700')


@contextmanager
def migration_lock():
    path_checked(str(BACKUPS))
    if not BACKUPS.exists():
        BACKUPS.mkdir(mode=0o700)
    root_private_directory(BACKUPS)
    lock = path_checked(str(BACKUPS / '.lock'))
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        private_file(lock, 0)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('Another migration or rollback is active') from None
        yield
    finally:
        os.close(fd)


def check_sources(plan, info):
    for f in plan['files'].values():
        p = path_checked(f['path'])
        require(p.is_file() and fingerprint(p) == f, 'Reviewed source or critical input drifted')
    for s in plan['services']:
        generated, _ = render(Path(s['source']), info)
        require(generated == s['plist'], 'Generated daemon differs from reviewed source')
        require(not Path(s['destination']).exists() and not loaded('system', s['label']), 'Destination is no longer empty')
        require(not disabled('system', s['label']), 'System service disable state changed since review')
        for d in s['domains']:
            require(loaded(d['domain'], s['label']) == d['loaded'] and disabled(d['domain'], s['label']) == d['disabled'],
                    'LaunchAgent state changed since review')


def backup_directory(plan):
    path_checked(str(BACKUPS))
    if not BACKUPS.exists():
        BACKUPS.mkdir(mode=0o700)
    root_private_directory(BACKUPS)
    backup = BACKUPS / plan['sha256']
    require(not backup.exists(), 'Backup already exists; inspect previous attempt before retrying')
    backup.mkdir(mode=0o700)
    write_private(backup / 'plan.json', canonical(plan))
    for s in plan['services']:
        write_private(backup / (s['label'] + '.agent.plist'), Path(s['source']).read_bytes())
    if not plan['quiescence'].get('ssh_host'):
        db = path_checked(plan['quiescence']['db'], Path(plan['user']['home']))
        with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(backup / 'coordinator.sqlite3')) as dst:
            src.backup(dst)
        os.chmod(backup / 'coordinator.sqlite3', 0o600)
    return backup


def save_journal(backup, journal):
    write_private(backup / 'journal.json', canonical(journal))


def _apply(plan, expected):
    info = validate_plan(plan, expected)
    check_sources(plan, info)
    require(database_state(plan['quiescence'], info, require_stopped=True) == plan['database'], 'Coordinator state changed since review')
    backup = backup_directory(plan)
    journal = {'schema': SCHEMA, 'phase': 'prepared', 'stopped': [], 'installed': []}
    save_journal(backup, journal)
    ordered = sorted(plan['services'], key=lambda s: (not s['label'].endswith('.coordinator'), s['label']))
    operation = 'stop-user-service'
    service = ordered[0]['label']
    try:
        for s in ordered:
            service = s['label']
            operation = 'stop-user-service'
            journal['stopped'].append(s['label'])
            save_journal(backup, journal)
            for d in s['domains']:
                if d['loaded']:
                    run(['/bin/launchctl', 'disable', d['domain'] + '/' + s['label']])
                    stop_service(d['domain'], s['label'])
                else:
                    run(['/bin/launchctl', 'disable', d['domain'] + '/' + s['label']], check=False)
                require(not loaded(d['domain'], s['label']), 'User service did not stop')
            operation = 'remove-user-plist'
            require(fingerprint(Path(s['source'])) == plan['files'][s['source']], 'LaunchAgent changed while stopping')
            Path(s['source']).unlink()
        operation = 'verify-quiescence'
        require(database_state(plan['quiescence'], info, require_stopped=True) == plan['database'], 'Coordinator changed during cutover; rollback required')
        for s in ordered:
            service = s['label']
            operation = 'install-system-service'
            destination = path_checked(s['destination'])
            require(not destination.exists() and not loaded('system', s['label']), 'System destination drifted during cutover')
            journal['installed'].append(s['label'])
            save_journal(backup, journal)
            write_private(destination, plistlib.dumps(s['plist'], sort_keys=True), mode=0o644)
            run(['/bin/launchctl', 'bootstrap', 'system', str(destination)])
            require(loaded('system', s['label']), 'System service did not load')
        journal['phase'] = 'installed'
        save_journal(backup, journal)
    except Exception as exc:
        journal['phase'] = 'rollback-required'
        journal['failure'] = {'operation': operation, 'service': service,
                              'kind': type(exc).__name__}
        save_journal(backup, journal)
        raise Refused('Cutover stopped at ' + operation + ' for ' + service +
                      '; use the digest-bound backup to roll back before retrying') from None
    return {'ok': True, 'backup': str(backup), 'installed': len(plan['services']),
            'cold_boot_verified': False, 'filevault': filevault()}


def _rollback(plan, expected):
    info = validate_plan(plan, expected)
    backup = path_checked(str(BACKUPS / expected))
    root_private_directory(backup)
    provenance = backup / 'plan.json'
    private_file(provenance, 0)
    require(json.loads(provenance.read_bytes()) == plan, 'Backup provenance differs from reviewed plan')
    journal_path = backup / 'journal.json'
    private_file(journal_path, 0)
    journal = json.loads(journal_path.read_bytes())
    require(journal.get('phase') in {'prepared', 'installed', 'rollback-required'}, 'Rollback already completed or journal invalid')
    require(set(journal.get('installed', [])) <= {s['label'] for s in plan['services']} and
            set(journal.get('stopped', [])) <= {s['label'] for s in plan['services']}, 'Invalid rollback journal')
    for s in plan['services']:
        original = path_checked(str(backup / (s['label'] + '.agent.plist')))
        private_file(original, 0)
        require(digest(original.read_bytes()) == plan['files'][s['source']]['sha256'], 'Backup plist digest mismatch')
        target = path_checked(s['destination'])
        if target.exists():
            require(s['label'] in journal['installed'] and target.read_bytes() == plistlib.dumps(s['plist'], sort_keys=True),
                    'Installed daemon drifted; manual reconciliation required')
        source = path_checked(s['source'])
        require(not source.exists() or fingerprint(source) == plan['files'][s['source']], 'Source LaunchAgent drifted; manual reconciliation required')
    source_paths = {s['source'] for s in plan['services']}
    for f in plan['files'].values():
        if f['path'] not in source_paths:
            p = path_checked(f['path'])
            require(p.is_file() and fingerprint(p) == f, 'Critical runtime input drifted; manual reconciliation required')
    require(database_state(plan['quiescence'], info, require_stopped=True)['pending'] == 0, 'Rollback requires quiescence')
    ordered = sorted(plan['services'], key=lambda s: (not s['label'].endswith('.coordinator'), s['label']))
    for s in ordered:
        if s['label'] in journal['installed']:
            if loaded('system', s['label']):
                stop_service('system', s['label'])
            if s['label'].endswith('.coordinator'):
                database_state(plan['quiescence'], info, require_stopped=True)
            target = Path(s['destination'])
            if target.exists():
                target.unlink()
    for s in plan['services']:
        if s['label'] not in journal['stopped']:
            continue
        original = backup / (s['label'] + '.agent.plist')
        f = plan['files'][s['source']]
        if not Path(s['source']).exists():
            write_private(Path(s['source']), original.read_bytes(), mode=f['mode'], uid=f['uid'], gid=f['gid'])
        for d in s['domains']:
            action = 'disable' if d['disabled'] else 'enable'
            run(['/bin/launchctl', action, d['domain'] + '/' + s['label']], check=False)
            if d['loaded'] and not loaded(d['domain'], s['label']):
                run(['/bin/launchctl', 'bootstrap', d['domain'], s['source']])
    journal['phase'] = 'rolled-back'
    save_journal(backup, journal)
    return {'ok': True, 'rolled_back': len(journal['stopped']), 'database_restored': False}


def apply(plan, expected):
    require_root()
    validate_plan(plan, expected)
    with migration_lock():
        return _apply(plan, expected)


def rollback(plan, expected):
    require_root()
    validate_plan(plan, expected)
    with migration_lock():
        return _rollback(plan, expected)


def probe(db):
    """Forced-command maintenance key target: counts/digests only, no task text."""
    require(platform.system() == 'Darwin', 'Probe requires the coordinator macOS host')
    info = user_info('axio')
    require(os.geteuid() == info['uid'], 'Probe must run as the coordinator service user')
    result = database_state({'db': db}, info)
    result['scheduler_loaded'] = any(loaded(d, 'com.snowgloves.hermes-pilot.coordinator') for d in
                                     ('system', 'gui/' + str(info['uid']), 'user/' + str(info['uid'])))
    return result


def status(plan, expected):
    validate_plan(plan, expected)
    services = []
    for s in plan['services']:
        p = path_checked(s['destination'])
        services.append({'label': s['label'], 'system_loaded': loaded('system', s['label']),
                         'system_disabled': disabled('system', s['label']),
                         'plist_matches': p.is_file() and p.read_bytes() == plistlib.dumps(s['plist'], sort_keys=True),
                         'user_loaded': any(loaded(d['domain'], s['label']) for d in s['domains'])})
    fv = filevault()
    return {'services': services, 'filevault': fv, 'cold_boot_verified': False,
            'startup_candidate': fv == 'off' and all(s['system_loaded'] and not s['system_disabled'] and s['plist_matches'] and not s['user_loaded'] for s in services)}


def load_review(path):
    p = path_checked(path)
    require(p.is_file() and p.stat().st_size <= 2_000_000, 'Plan is missing or too large')
    owners = {0}
    for user in USERS:
        try:
            owners.add(pwd.getpwnam(user).pw_uid)
        except KeyError:
            pass
    require(p.stat().st_uid in owners and stat.S_IMODE(p.stat().st_mode) & 0o077 == 0,
            'Plan must be private and owned by a service user or root')
    return json.loads(p.read_bytes())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'plan'):
        p = commands.add_parser(name)
        p.add_argument('--user', choices=sorted(USERS), required=True)
        p.add_argument('--service', action='append', required=True, help='Exact allowlisted label; repeat explicitly')
        p.add_argument('--quiescence-db', required=True)
        p.add_argument('--quiescence-ssh-host', choices=sorted(SSH_HOSTS))
        p.add_argument('--quiescence-identity-file', help='Separate restricted maintenance identity; never transport key')
        p.add_argument('--critical-file', action='append', default=[])
        if name == 'plan':
            p.add_argument('--output', required=True, help='New private review plan; never a tracked file')
    for name in ('apply', 'status', 'rollback'):
        p = commands.add_parser(name)
        p.add_argument('--plan', required=True)
        p.add_argument('--expect-sha256', required=True, help='Digest from independent plan review')
    p = commands.add_parser('probe', help='Read-only fixed-command maintenance key target')
    p.add_argument('--quiescence-db', required=True)
    args = ap.parse_args(argv)
    try:
        if args.command in ('inspect', 'plan'):
            result = make_plan(args.user, args.service, args.quiescence_db, args.quiescence_ssh_host, args.critical_file, args.quiescence_identity_file)
            if args.command == 'plan':
                p = path_checked(args.output, Path(result['user']['home']))
                private_parent(p, result['user'])
                require(not p.exists(), 'Refusing to overwrite an existing review plan')
                write_private(p, canonical(result), uid=result['user']['uid'], gid=result['user']['gid'])
            output = {'ok': True, 'sha256': result['sha256'], 'services': [s['label'] for s in result['services']],
                      'filevault': result['filevault'], 'cold_boot_verified': False}
        elif args.command == 'probe':
            output = probe(args.quiescence_db)
        else:
            plan = load_review(args.plan)
            output = globals()[args.command](plan, args.expect_sha256)
        print(json.dumps(output, sort_keys=True))
        return 0
    except Refused as exc:
        print(json.dumps({'ok': False, 'reason': str(exc)}), file=sys.stderr)
    except Exception:
        print(json.dumps({'ok': False, 'reason': 'Invalid input or host operation; inspect private host logs'}), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Read-only pinned toolchain inspection and package-manager planning."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
TOOLS = {'brew', 'git', 'gh', 'node', 'npm', 'python3', 'uv', 'codex', 'claude'}
MAX_JSON = 2_000_000
MAX_FILE = 512_000_000
MAX_OUTPUT = 16384
VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?')
PREFIX = {'brew': r'Homebrew ', 'git': r'git version ', 'gh': r'gh version ',
          'node': 'v', 'npm': '', 'python3': r'Python ', 'uv': r'uv ',
          'codex': r'codex-cli ', 'claude': ''}


def parse_version(tool, raw):
    first = raw.decode('utf-8', 'strict').splitlines()[0]
    if len(first) > 256:
        raise ValueError('unexpected version output')
    match = re.fullmatch(PREFIX[tool] + r'(\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)(?: \([^\r\n]+\))?', first)
    if not match:
        raise ValueError('unexpected version output')
    return match.group(1)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate input key')
        result[key] = value
    return result


def absolute(value):
    if not isinstance(value, str) or not value or os.pathsep in value or any(ord(c) < 32 for c in value):
        raise ValueError('invalid absolute path')
    path = Path(value)
    if not path.is_absolute() or str(path) != value or '..' in path.parts:
        raise ValueError('noncanonical path')
    if path.resolve() != path:
        raise ValueError('symlink path')
    return path


def fingerprint(value, limit=MAX_FILE):
    path = absolute(value)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('unbounded or nonregular input')
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError('unbounded input')
            digest.update(chunk)
        after = os.fstat(fd)
        current = path.stat(follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise ValueError('input changed')
        return digest.hexdigest()
    finally:
        os.close(fd)


def read_json(value, expected):
    path = absolute(value)
    if not re.fullmatch('[0-9a-f]{64}', expected or ''):
        raise ValueError('reviewed digest required')
    # The second hash and bounded read also reject replacement during loading.
    first = fingerprint(value, MAX_JSON)
    if first != expected:
        raise ValueError('reviewed input changed')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_JSON:
            raise ValueError('unbounded or nonregular input')
        raw = stream.read(MAX_JSON + 1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if identity(before) != identity(after):
        raise ValueError('input changed')
    if len(raw) > MAX_JSON or sha(raw) != first or fingerprint(value, MAX_JSON) != first:
        raise ValueError('reviewed input changed')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite input')))


def load_release(path, digest):
    value = read_json(path, digest)
    if (not isinstance(value, dict) or set(value) != {'schema', 'node', 'system', 'machine', 'tools'}
            or value['schema'] != 'snowgloves.toolchain-release.v1'
            or not isinstance(value['node'], str) or not re.fullmatch('[a-z][a-z0-9-]{0,62}', value['node'])
            or value['system'] not in ('Darwin', 'Linux') or value['machine'] not in ('arm64', 'aarch64', 'x86_64')
            or not isinstance(value['tools'], list) or not 1 <= len(value['tools']) <= len(TOOLS)):
        raise ValueError('invalid release')
    ids = set()
    for tool in value['tools']:
        if (not isinstance(tool, dict) or set(tool) != {'id', 'path', 'sha256', 'version'}
                or not isinstance(tool['id'], str) or tool['id'] not in TOOLS or tool['id'] in ids
                or not isinstance(tool['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', tool['sha256'])
                or not isinstance(tool['version'], str) or not VERSION.fullmatch(tool['version'])):
            raise ValueError('invalid tool pin')
        absolute(tool['path'])
        ids.add(tool['id'])
    if 'npm' in ids and 'node' not in ids:
        raise ValueError('npm requires a pinned node')
    return value


def environment(release):
    # Do not forward provider credentials, NODE_OPTIONS, Python paths or npm config.
    ordered = sorted(release['tools'], key=lambda t: 0 if t['id'] == 'node' else 1)
    directories = list(dict.fromkeys(str(Path(t['path']).parent) for t in ordered))
    return {'PATH': os.pathsep.join(directories + ['/usr/bin', '/bin', '/usr/sbin', '/sbin']),
            'HOME': '/var/empty', 'LC_ALL': 'C', 'HOMEBREW_NO_AUTO_UPDATE': '1',
            'HOMEBREW_NO_ANALYTICS': '1', 'HOMEBREW_NO_ENV_HINTS': '1',
            'NPM_CONFIG_USERCONFIG': '/dev/null', 'NPM_CONFIG_GLOBALCONFIG': '/var/empty/snowgloves-disabled-global.npmrc'}


def bounded_run(argv, env, timeout=10):
    child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, start_new_session=True)
    output = bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, True)
            selector.register(child.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise ValueError('version probe timed out')
                for key, _ in selector.select(min(.1, deadline - time.monotonic())):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > MAX_OUTPUT:
                        raise ValueError('version output exceeded bound')
                    if key.data:
                        output.extend(chunk)
        code = child.wait(timeout=max(.01, deadline - time.monotonic()))
        if code != 0:
            raise ValueError('version probe failed')
        return bytes(output)
    finally:
        # Also end descendants which retained a pipe after the entry process exited.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        child.stdout.close()
        child.stderr.close()


def inspect_release(release, probe=False, runner=bounded_run):
    if release['system'] != platform.system() or release['machine'] != platform.machine():
        raise ValueError('release does not match this host')
    rows = []
    pins = {t['id']: t for t in release['tools']}
    verified = {}
    for tool in release['tools']:
        try:
            verified[tool['id']] = fingerprint(tool['path']) == tool['sha256'] and os.access(tool['path'], os.X_OK)
        except (OSError, ValueError):
            verified[tool['id']] = False
    for tool in release['tools']:
        row = {'id': tool['id'], 'path': tool['path'], 'expected_version': tool['version'],
               'entry_sha256': tool['sha256'], 'status': 'held', 'reason': 'Entry bytes or presence do not match the release'}
        if verified[tool['id']]:
            row['reason'] = 'Entry bytes match; version is unprobed'
            if probe:
                try:
                    # npm's JS entry is executed with the pinned Node, never ambient PATH.
                    if tool['id'] == 'npm':
                        if not verified['node']:
                            raise ValueError('node dependency drift')
                        argv = [pins['node']['path'], tool['path'], '--version']
                    else:
                        argv = [tool['path'], '--version']
                    raw = runner(argv, environment(release))
                    observed_version = parse_version(tool['id'], raw)
                    if observed_version != tool['version']:
                        raise ValueError('version mismatch')
                    if fingerprint(tool['path']) != tool['sha256']:
                        raise ValueError('entry changed during probe')
                    if tool['id'] == 'npm' and fingerprint(pins['node']['path']) != pins['node']['sha256']:
                        raise ValueError('node changed during probe')
                    row.update(status='pass', reason='Exact entry bytes and bounded version probe match', observed_version=observed_version)
                except (OSError, ValueError, UnicodeError, IndexError, subprocess.SubprocessError):
                    row['reason'] = 'Version or entry binding failed; raw output withheld'
        rows.append(row)
    return {'schema': 'snowgloves.toolchain-inspection.v1', 'node': release['node'], 'tools': rows,
            'passed': all(r['status'] == 'pass' for r in rows),
            'scope': 'Selected entry files and versions; not full distribution, authentication, service or fleet readiness'}


def bound_file(record):
    if (not isinstance(record, dict) or set(record) != {'path', 'sha256'}
            or not isinstance(record['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
        raise ValueError('invalid source binding')
    if fingerprint(record['path']) != record['sha256']:
        raise ValueError('source bytes changed')
    return record['path']


def make_plan(release, release_digest, request, root):
    root = absolute(root)
    if not root.is_dir() or root.stat().st_uid != os.geteuid():
        raise ValueError('existing owned root required')
    if not isinstance(release_digest, str) or not re.fullmatch('[0-9a-f]{64}', release_digest):
        raise ValueError('reviewed release digest required')
    if (not isinstance(request, dict) or set(request) != {'schema', 'steps'}
            or request['schema'] != 'snowgloves.toolchain-request.v1'
            or not isinstance(request['steps'], list) or len(request['steps']) > 32):
        raise ValueError('invalid tooling request')
    pins = {t['id']: t for t in release['tools']}
    steps = []
    used = set()
    for step in request['steps']:
        if not isinstance(step, dict):
            raise ValueError('invalid adapter step')
        adapter = step.get('adapter')
        keys = {'uv-venv': {'adapter', 'target'}, 'npm-ci': {'adapter', 'target', 'package', 'lock', 'network'},
                'homebrew-bottle': {'adapter', 'artifact', 'dependencies'}}
        if not isinstance(adapter, str) or adapter not in keys or set(step) != keys[adapter]:
            raise ValueError('unsupported or open adapter contract')
        manager = {'uv-venv': 'uv', 'npm-ci': 'npm', 'homebrew-bottle': 'brew'}[adapter]
        if manager not in pins:
            raise ValueError('package manager is not pinned')
        sources = []
        target = None
        held = []
        if adapter != 'homebrew-bottle':
            name = step['target']
            if not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9-]{0,62}', name) or name in used:
                raise ValueError('invalid or duplicate owned target')
            target = root / name
            if target.exists() or target.is_symlink():
                raise ValueError('target already exists; reconcile instead of overwriting')
            used.add(name)
        if adapter == 'uv-venv':
            if 'python3' not in pins:
                raise ValueError('interpreter not pinned')
            argv = [pins['uv']['path'], '--no-config', '--offline', '--no-cache', '--no-python-downloads',
                    'venv', '--no-project', '--python', pins['python3']['path'], str(target)]
            held.append('Application must recheck pinned uv/interpreter bytes and publish an owned stage receipt')
        elif adapter == 'npm-ci':
            if 'node' not in pins or type(step['network']) is not bool:
                raise ValueError('node and explicit network policy required')
            package = bound_file(step['package']); lock = bound_file(step['lock'])
            sources = [step['package'], step['lock']]
            package_value = read_json(package, step['package']['sha256'])
            lock_value = read_json(lock, step['lock']['sha256'])
            if (not isinstance(package_value, dict) or not isinstance(lock_value, dict)
                    or lock_value.get('lockfileVersion') not in (2, 3) or not isinstance(lock_value.get('packages'), dict)):
                raise ValueError('locked npm project required')
            if package_value.get('workspaces') or any(k in package_value for k in ('pnpm', 'overrides')):
                raise ValueError('unbounded npm project policy')
            for name, item in lock_value['packages'].items():
                if not isinstance(name, str) or not isinstance(item, dict):
                    raise ValueError('invalid npm lock entry')
                if not name:
                    continue
                if (not name.startswith('node_modules/') or '..' in Path(name).parts
                        or item.get('link') or not isinstance(item.get('version'), str)
                        or not re.fullmatch(r'https://registry\.npmjs\.org/[^\s?#]+', item.get('resolved', ''))
                        or not re.fullmatch(r'sha512-[A-Za-z0-9+/]+={0,2}', item.get('integrity', ''))):
                    raise ValueError('unpinned or nonregistry npm dependency')
                if len(base64.b64decode(item['integrity'][7:], validate=True)) != 64:
                    raise ValueError('invalid npm integrity')
            argv = [pins['node']['path'], pins['npm']['path'], 'ci', '--prefix', str(target),
                    '--ignore-scripts', '--no-audit', '--no-fund', '--cache', str(target / '.cache')]
            if not step['network']:
                argv.append('--offline')
            held.append('Application must stage these exact package/lock bytes, recheck entries, and retain failed stage evidence')
        else:
            artifact = bound_file(step['artifact']); sources = [step['artifact']]
            if not artifact.endswith('.bottle.tar.gz') or not isinstance(step['dependencies'], list):
                raise ValueError('local Homebrew bottle and explicit dependency pins required')
            if any(not isinstance(i, str) or i not in pins for i in step['dependencies']) or len(set(step['dependencies'])) != len(step['dependencies']):
                raise ValueError('unknown or duplicate Homebrew dependency')
            argv = [pins['brew']['path'], 'install', '--formula', '--force-bottle', '--skip-post-install', artifact]
            held.append('Shared Homebrew prefix and complete bottle dependency/formula identity require separate review; no automatic uninstall')
        steps.append({'adapter': adapter, 'argv': argv, 'target': str(target) if target else None,
                      'sources': sources, 'held': held, 'executable': False})
    result = {'schema': 'snowgloves.toolchain-plan.v1', 'node': release['node'], 'root': str(root),
              'release_sha256': release_digest, 'request_canonical_sha256': sha(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()),
              'planner_sha256': fingerprint(str(Path(__file__).resolve())),
              'steps': steps, 'application_supported': False,
              'scope': 'Deterministic adapter review plan; execution/journal/fresh-machine acceptance remains open'}
    result['digest'] = sha(json.dumps(result, sort_keys=True, separators=(',', ':')).encode())
    return result


def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError('invalid invocation')
    parser = Parser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--release-digest', required=True)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--request')
    parser.add_argument('--request-digest')
    parser.add_argument('--root')
    try:
        args = parser.parse_args(argv)
        release = load_release(args.release, args.release_digest)
        result = inspect_release(release, args.probe)
        if args.request:
            request = read_json(args.request, args.request_digest)
            result['plan'] = make_plan(release, args.release_digest, request, args.root)
        elif args.request_digest or args.root:
            raise ValueError('request required')
        print(json.dumps(result, indent=2))
        return 0 if result['passed'] else 2
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(json.dumps({'schema': 'snowgloves.toolchain-inspection.v1', 'passed': False,
                          'error': 'Invalid, changed or unsafe toolchain inputs; raw output withheld'}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())

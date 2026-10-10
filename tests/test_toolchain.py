import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys

import pytest

spec = importlib.util.spec_from_file_location('toolchain', Path(__file__).resolve().parents[1] / 'scripts/fleet/toolchain.py')
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)


@pytest.fixture
def release(tmp_path):
    records = []
    for name in ('brew', 'uv', 'python3', 'node', 'npm'):
        path = tmp_path / name
        path.write_text('#!/bin/sh\necho 2.3.4\n'); path.chmod(0o700)
        records.append({'id': name, 'path': str(path), 'sha256': tools.fingerprint(str(path)), 'version': '2.3.4'})
    value = {'schema': 'snowgloves.toolchain-release.v1', 'node': 'controller-a', 'system': platform.system(),
             'machine': platform.machine(), 'tools': records}
    return value


def request(*steps):
    return {'schema': 'snowgloves.toolchain-request.v1', 'steps': list(steps)}


def bound(tmp_path, name, value):
    path = tmp_path / name; path.write_text(json.dumps(value))
    return {'path': str(path), 'sha256': tools.fingerprint(str(path))}


def npm_step(tmp_path):
    package = bound(tmp_path, 'package.json', {'name': 'fixture', 'version': '1.0.0', 'private': True})
    lock = bound(tmp_path, 'package-lock.json', {'lockfileVersion': 3, 'packages': {'': {'name': 'fixture'},
        'node_modules/dep': {'version': '1.0.0', 'resolved': 'https://registry.npmjs.org/dep/-/dep-1.0.0.tgz',
                             'integrity': 'sha512-'+base64.b64encode(b'x'*64).decode()}}})
    return {'adapter': 'npm-ci', 'target': 'npm-env', 'package': package, 'lock': lock, 'network': False}


def test_default_inspect_is_no_execution_or_mutation(release, tmp_path):
    before = {str(p): p.read_bytes() for p in tmp_path.iterdir()}
    def forbidden(*args):
        pytest.fail('default inspection executed a binary')
    result = tools.inspect_release(release, runner=forbidden)
    assert not result['passed'] and all(r['status'] == 'held' for r in result['tools'])
    assert before == {str(p): p.read_bytes() for p in tmp_path.iterdir()}


def test_explicit_version_probe_uses_pinned_node_and_drops_ambient_credentials(release, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-secret')
    monkeypatch.setenv('NODE_OPTIONS', '--import=unreviewed.js')
    calls = []
    def runner(argv, env):
        assert 'OPENAI_API_KEY' not in env and 'NODE_OPTIONS' not in env
        assert env['NPM_CONFIG_USERCONFIG'] != env['NPM_CONFIG_GLOBALCONFIG']
        assert env['PATH'].split(':')[0] == str(Path(release['tools'][3]['path']).parent)
        calls.append(argv)
        name = Path(argv[1]).name if len(argv) == 3 else Path(argv[0]).name
        prefix = {'brew': 'Homebrew ', 'uv': 'uv ', 'python3': 'Python ', 'node': 'v', 'npm': ''}[name]
        return (prefix + '2.3.4\n').encode()
    assert tools.inspect_release(release, True, runner)['passed']
    assert calls[-1] == [release['tools'][3]['path'], release['tools'][4]['path'], '--version']


def test_drift_refuses_execution_and_never_echoes_output(release):
    Path(release['tools'][0]['path']).write_text('changed')
    calls = []
    def runner(argv, env):
        calls.append(argv); return b'synthetic-secret version 9.9.9\n'
    result = tools.inspect_release(release, True, runner)
    assert release['tools'][0]['path'] not in [c[0] for c in calls]
    assert not result['passed'] and 'synthetic-secret' not in json.dumps(result)


def test_drifted_node_also_refuses_npm_wrapper(release):
    Path(release['tools'][3]['path']).write_text('changed')
    calls = []
    def runner(argv, env):
        calls.append(argv); return b'2.3.4\n'
    result = tools.inspect_release(release, True, runner)
    assert all(release['tools'][4]['path'] not in c for c in calls)
    assert result['tools'][-1]['status'] == 'held'


def test_uv_plan_is_deterministic_offline_pinned_and_creates_nothing(release, tmp_path):
    value = request({'adapter': 'uv-venv', 'target': 'python-env'})
    one = tools.make_plan(release, 'a'*64, value, str(tmp_path))
    assert one == tools.make_plan(release, 'a'*64, value, str(tmp_path))
    assert '--offline' in one['steps'][0]['argv'] and '--no-python-downloads' in one['steps'][0]['argv']
    assert release['tools'][2]['path'] in one['steps'][0]['argv']
    assert not (tmp_path/'python-env').exists() and not one['application_supported']


@pytest.mark.parametrize('target', ['../escape', '/escape', '--option', 'two/levels', 'bad\nname'])
def test_target_traversal_option_injection_and_unbounded_destinations_are_refused(release, tmp_path, target):
    with pytest.raises(ValueError):
        tools.make_plan(release, 'a'*64, request({'adapter': 'uv-venv', 'target': target}), str(tmp_path))


def test_existing_and_duplicate_targets_are_not_overwritten(release, tmp_path):
    (tmp_path/'existing').mkdir()
    for value in [request({'adapter': 'uv-venv', 'target': 'existing'}),
                  request(*[{'adapter': 'uv-venv', 'target': 'same'}]*2)]:
        with pytest.raises(ValueError):
            tools.make_plan(release, 'a'*64, value, str(tmp_path))


def test_npm_lock_pins_and_network_policy_are_bound_without_installing(release, tmp_path):
    step = npm_step(tmp_path)
    one = tools.make_plan(release, 'a'*64, request(step), str(tmp_path))
    argv = one['steps'][0]['argv']
    assert '--offline' in argv and '--ignore-scripts' in argv and '--no-audit' in argv
    step['network'] = True
    two = tools.make_plan(release, 'a'*64, request(step), str(tmp_path))
    assert '--offline' not in two['steps'][0]['argv'] and two['digest'] != one['digest']
    assert not (tmp_path/'npm-env').exists()


@pytest.mark.parametrize('change', ['foreign-registry', 'git-source', 'missing-integrity', 'false-integrity', 'link'])
def test_unpinned_npm_inputs_cannot_be_promoted_to_a_plan(release, tmp_path, change):
    step = npm_step(tmp_path); path = Path(step['lock']['path']); value = json.loads(path.read_text())
    dep = value['packages']['node_modules/dep']
    if change == 'foreign-registry': dep['resolved'] = 'https://foreign.example/dep.tgz'
    if change == 'git-source': dep['resolved'] = 'git+https://github.com/example/repo'
    if change == 'missing-integrity': dep.pop('integrity')
    if change == 'false-integrity': dep['integrity'] = 'sha512-AAAA'
    if change == 'link': dep['link'] = True
    path.write_text(json.dumps(value)); step['lock']['sha256'] = tools.fingerprint(str(path))
    with pytest.raises(ValueError): tools.make_plan(release, 'a'*64, request(step), str(tmp_path))


def test_changed_source_and_symlinked_root_require_reconciliation(release, tmp_path):
    step = npm_step(tmp_path); Path(step['package']['path']).write_text('changed')
    with pytest.raises(ValueError): tools.make_plan(release, 'a'*64, request(step), str(tmp_path))
    alias = tmp_path/'alias'; alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError): tools.make_plan(release, 'a'*64, request(), str(alias))


def test_homebrew_review_is_byte_bound_and_held_for_shared_prefix(release, tmp_path):
    artifact = tmp_path/'fixture.bottle.tar.gz'; artifact.write_bytes(b'synthetic bottle')
    step = {'adapter': 'homebrew-bottle', 'artifact': {'path': str(artifact), 'sha256': tools.fingerprint(str(artifact))}, 'dependencies': ['node']}
    result = tools.make_plan(release, 'a'*64, request(step), str(tmp_path))
    assert result['steps'][0]['held'] and not result['steps'][0]['executable']
    assert '--ignore-dependencies' not in result['steps'][0]['argv']
    artifact.write_bytes(b'changed')
    with pytest.raises(ValueError): tools.make_plan(release, 'a'*64, request(step), str(tmp_path))


def test_duplicate_json_unknown_tools_and_unbound_release_are_invalid(release, tmp_path):
    path = tmp_path/'release.json'; path.write_text(json.dumps(release))
    with pytest.raises(ValueError): tools.load_release(str(path), '0'*64)
    value = dict(release); value['tools'] = [dict(release['tools'][0], id='unknown')]
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError): tools.load_release(str(path), tools.fingerprint(str(path)))
    path.write_text('{"schema":"one","schema":"two"}')
    with pytest.raises(ValueError): tools.load_release(str(path), tools.fingerprint(str(path)))


@pytest.mark.parametrize('body', ['import time; time.sleep(1)', 'import sys; sys.stdout.write("x"*30000)',
                                  'import os,time; p=os.fork(); os._exit(0) if p else time.sleep(1)'])
def test_real_probe_bounds_time_output_and_pipe_holding_descendants(body):
    with pytest.raises(ValueError):
        tools.bounded_run([sys.executable, '-c', body], {'PATH': '/usr/bin:/bin'}, timeout=.15)


def test_invalid_cli_exit_three_does_not_echo_invocation(capsys):
    assert tools.main(['--unknown=synthetic-secret']) == 3
    assert 'synthetic-secret' not in capsys.readouterr().out


@pytest.mark.parametrize('name,output,version', [
    ('node', 'v22.23.3', '22.23.3'), ('npm', '10.9.9', '10.9.9'),
    ('git', 'git version 2.56.0', '2.56.0'), ('brew', 'Homebrew 7.0.9', '7.0.9'),
    ('gh', 'gh version 2.102.0 (2026-09-30)', '2.102.0'), ('python3', 'Python 3.14.8', '3.14.8'),
    ('uv', 'uv 0.12.24 (Homebrew 2026-10-08 aarch64-apple-darwin)', '0.12.24'),
    ('codex', 'codex-cli 0.160.0', '0.160.0'), ('claude', '2.1.287 (Claude Code)', '2.1.287')])
def test_actual_upstream_version_shapes_are_supported(name, output, version):
    assert tools.parse_version(name, (output+'\n').encode()) == version


def test_arbitrary_version_substrings_do_not_prove_tool_identity():
    with pytest.raises(ValueError): tools.parse_version('node', b'arbitrary version 22.23.3\n')

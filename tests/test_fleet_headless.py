"""Dependency-free migration tests: no actual launchctl, sudo, SSH or host writes."""
import copy
from contextlib import ExitStack, closing
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('fleet_headless', Path(__file__).resolve().parents[1] / 'scripts/fleet/headless.py')
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)
ORIGINAL_DISABLED = h.disabled


class Headless(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(self.tmp).resolve()
        self.home = self.root / 'axio'
        self.home.mkdir(mode=0o700)
        self.agents = self.home / 'Library/LaunchAgents'
        self.agents.mkdir(parents=True, mode=0o700)
        self.logs = self.home / 'logs'
        self.logs.mkdir(mode=0o700)
        self.daemons = self.root / 'daemons'
        self.daemons.mkdir(mode=0o755)
        self.info = {'name': 'axio', 'uid': os.getuid(), 'gid': os.getgid(), 'home': str(self.home)}
        self.exe = self.home / 'python3'
        self.exe.write_text('#!/bin/sh\nexit 0\n')
        self.exe.chmod(0o700)
        self.script = self.home / 'fleet_coordinator.py'
        self.script.write_text('# Read-only tests do not execute this file.\n')
        self.script.chmod(0o600)
        self.config = self.home / 'config.json'
        self.config.write_text(json.dumps({'token': 'PRIVATE_CONFIG_CONTENT'}))
        self.config.chmod(0o600)
        self.db = self.home / 'fleet.sqlite3'
        with closing(sqlite3.connect(self.db)) as c:
            c.execute('CREATE TABLE tasks(id TEXT,status TEXT,updated REAL,worker TEXT,attempt_id TEXT,lease_hash TEXT,deadline REAL)')
            c.commit()
        self.db.chmod(0o600)
        self.live = set()
        self.disabled = set()
        self.commands = []
        self.bootstrap_error = False
        self.probe = {'ok': True, 'pending': 0, 'state_sha256': 'a' * 64}
        self.original_path_checked = h.path_checked
        self.original_private_file = h.private_file
        self.original_write = h.write_private
        self.original_db_state = h.database_state
        def checked(value, within=None):
            if within == Path('/Users/axio'):
                within = self.home
            return self.original_path_checked(value, within)
        self.stack.enter_context(patch.object(h, 'path_checked', checked))
        self.stack.enter_context(patch.object(h, 'DAEMONS', self.daemons))
        self.stack.enter_context(patch.object(h, 'BACKUPS', self.root / 'backups'))
        self.stack.enter_context(patch.object(h.platform, 'system', lambda: 'Darwin'))
        self.stack.enter_context(patch.object(h.platform, 'node', lambda: 'coding01-test'))
        self.stack.enter_context(patch.object(h, 'user_info', lambda name: dict(self.info)))
        self.stack.enter_context(patch.object(h, 'require_root', lambda: None))
        self.stack.enter_context(patch.object(h, 'root_private_directory', lambda p: self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)))
        self.stack.enter_context(patch.object(h, 'private_file', lambda p, uid, **kw: self.original_private_file(p, os.getuid() if uid == 0 else uid, **kw)))
        self.stack.enter_context(patch.object(h, 'write_private', lambda p, data, **kw: self.original_write(p, data, **dict(kw, uid=os.getuid(), gid=os.getgid()))))
        self.stack.enter_context(patch.object(h, 'database_state', lambda *a, **kw: dict(self.probe)))
        self.stack.enter_context(patch.object(h, 'filevault', lambda: 'off'))
        self.stack.enter_context(patch.object(h, 'loaded', lambda domain, label: (domain, label) in self.live))
        self.stack.enter_context(patch.object(h, 'disabled', lambda domain, label: (domain, label) in self.disabled))
        self.stack.enter_context(patch.object(h, 'run', self.fake_run))
        self.label = 'com.snowgloves.hermes-pilot.coordinator'
        self.source = self.make_agent(self.label)
        self.live.add(('gui/' + str(os.getuid()), self.label))

    def make_agent(self, label, **kw):
        raw = {'Label': label, 'ProgramArguments': [str(self.exe), str(self.script), '--config', str(self.config)],
               'WorkingDirectory': str(self.home), 'EnvironmentVariables': {'SNOWGLOVES_DATA': str(self.home)},
               'StandardOutPath': str(self.logs / (label + '.out')), 'StandardErrorPath': str(self.logs / (label + '.err')),
               'RunAtLoad': True, 'KeepAlive': True}
        raw.update(kw)
        source = self.agents / (label + '.plist')
        source.write_bytes(plistlib.dumps(raw))
        source.chmod(0o600)
        return source

    def fake_run(self, command, **kw):
        self.commands.append(command)
        if command[0] == '/bin/launchctl':
            action = command[1]
            if action in {'disable', 'enable', 'bootout'}:
                domain, label = command[-1].rsplit('/', 1)
                if action == 'disable':
                    self.disabled.add((domain, label))
                elif action == 'enable':
                    self.disabled.discard((domain, label))
                else:
                    self.live.discard((domain, label))
            elif action == 'bootstrap':
                if self.bootstrap_error and command[2] == 'system':
                    raise h.Refused('Service command failed; inspect private host logs')
                raw = plistlib.loads(Path(command[3]).read_bytes())
                if command[2] == 'system':
                    self.assertFalse(any(domain != 'system' for domain, _label in self.live))
                    self.assertEqual(raw['UserName'], 'axio')
                self.live.add((command[2], raw['Label']))
        return subprocess.CompletedProcess(command, 0, b'', b'')

    def plan(self, *labels):
        return h.make_plan('axio', list(labels or (self.label,)), str(self.db))

    def test_nonroot_absolute_private_generated_service(self):
        generated, files = h.render(self.source, self.info)
        self.assertEqual(generated['UserName'], 'axio')
        self.assertEqual(generated['EnvironmentVariables']['HOME'], str(self.home))
        self.assertEqual(generated['EnvironmentVariables']['USER'], 'axio')
        self.assertGreaterEqual(generated['ThrottleInterval'], 30)
        self.assertEqual(generated['Umask'], 0o077)
        self.assertIn(str(self.config), files)
        self.assertNotIn('PRIVATE_CONFIG_CONTENT', json.dumps(generated))
        self.assertNotIn('PRIVATE_CONFIG_CONTENT', json.dumps(files))

    def test_scheduled_renewal_does_not_become_continuous(self):
        label = 'com.snowgloves.hermes-pilot.tls-renew'
        source = self.make_agent(label, StartCalendarInterval={'Hour': 3, 'Minute': 12}, KeepAlive=False, RunAtLoad=False)
        generated, _ = h.render(source, self.info)
        self.assertFalse(generated['KeepAlive'])
        self.assertFalse(generated['RunAtLoad'])
        self.assertEqual(generated['StartCalendarInterval'], {'Hour': 3, 'Minute': 12})

    def test_transport_and_http_mcp_are_explicitly_allowlisted(self):
        self.assertIn('fr.heyzack.snowgloves.coding02-transport', h.SERVICES['maccoding2'])
        self.assertIn('fr.heyzack.snowgloves.coding02-worker', h.SERVICES['maccoding2'])
        self.assertIn('com.snowgloves.hermes-pilot.mcp-http', h.SERVICES['axio'])
        self.assertNotIn('com.temperance.engine.pulse-compat', h.SERVICES['axio'])

    def test_env_node_entrypoint_gets_explicit_hashed_interpreter(self):
        node = self.home / 'node'
        node.write_text('#!/bin/sh\nexit 0\n')
        node.chmod(0o700)
        self.exe.write_text('#!/usr/bin/env node\n// fixture entrypoint\n')
        original = h.executable_path
        with patch.object(h, 'executable_path', lambda value, home: node if value == '/opt/homebrew/bin/node' else original(value, home)):
            generated, files = h.render(self.source, self.info)
        self.assertEqual(generated['ProgramArguments'][:2], [str(node), str(self.exe)])
        self.assertIn(str(node), files)
        self.exe.write_text('#!/usr/bin/env python3\n')
        with self.assertRaisesRegex(h.Refused, 'explicit interpreter'):
            h.render(self.source, self.info)

    def test_inline_secrets_and_interactive_dependencies_refused_without_echo(self):
        for env in ({'API_TOKEN': 'VERY_SECRET'}, {'HOME': '/Users/root'}, {'PATH': '.:/usr/bin'},
                    {'SSH_AUTH_SOCK': '/tmp/session.sock'}, {'NOTE': 'BEGIN RSA PRIVATE' + ' KEY'}):
            with self.subTest(env=tuple(env)):
                self.make_agent(self.label, EnvironmentVariables=env)
                with self.assertRaises(h.Refused) as caught:
                    h.render(self.source, self.info)
                self.assertNotIn('VERY_SECRET', str(caught.exception))

    def test_token_file_allowed_but_unsafe_mode_refused(self):
        token = self.home / 'app.token'
        token.write_text('PRIVATE_TOKEN_CONTENT')
        token.chmod(0o600)
        self.make_agent(self.label, EnvironmentVariables={'APP_TOKEN_FILE': str(token)})
        generated, files = h.render(self.source, self.info)
        self.assertIn(str(token), files)
        self.assertNotIn('PRIVATE_TOKEN_CONTENT', json.dumps(generated))
        token.chmod(0o644)
        with self.assertRaisesRegex(h.Refused, 'permissions'):
            h.render(self.source, self.info)

    def test_gui_labels_properties_args_and_wrappers_refused(self):
        for change in ({'Label': 'com.grok.app'}, {'LimitLoadToSessionType': 'Aqua'},
                       {'ProgramArguments': ['/usr/bin/open', '/Applications/Grok.app']},
                       {'ProcessType': 'Interactive'}, {'KeepAlive': {'SuccessfulExit': False}}):
            with self.subTest(change=tuple(change)):
                self.make_agent(self.label, **change)
                with self.assertRaises(h.Refused):
                    h.render(self.source, self.info)
        self.make_agent(self.label)
        self.script.write_text('import subprocess\nsubprocess.run(["osascript"])\n')
        with self.assertRaisesRegex(h.Refused, 'Wrapper'):
            h.render(self.source, self.info)

    def test_source_log_config_symlinks_and_traversal_refused(self):
        for value in ('relative.plist', str(self.home) + '/../outside', str(self.home) + '//logs/file'):
            with self.assertRaises(h.Refused):
                h.path_checked(value, self.home)
        alias = self.home / 'alias'
        alias.symlink_to(self.logs, target_is_directory=True)
        self.make_agent(self.label, StandardOutPath=str(alias / 'output.log'))
        with self.assertRaisesRegex(h.Refused, 'Symlink'):
            h.render(self.source, self.info)
        self.make_agent(self.label)
        self.config.chmod(0o644)
        with self.assertRaisesRegex(h.Refused, 'permissions'):
            h.render(self.source, self.info)

    def test_missing_config_and_private_log_bounds_refused(self):
        self.make_agent(self.label, ProgramArguments=[str(self.exe), '--config', str(self.home / 'missing.json')])
        with self.assertRaisesRegex(h.Refused, 'missing'):
            h.render(self.source, self.info)
        self.make_agent(self.label)
        self.logs.chmod(0o755)
        with self.assertRaisesRegex(h.Refused, 'private'):
            h.render(self.source, self.info)

    def test_digest_host_account_domain_and_path_tampering(self):
        plan = self.plan()
        with self.assertRaisesRegex(h.Refused, 'digest'):
            h.validate_plan(plan, 'b' * 64)
        for field, value in (('host', 'other-host'), ('user', dict(self.info, uid=self.info['uid'] + 1))):
            changed = copy.deepcopy(plan)
            changed[field] = value
            changed['sha256'] = h.digest(h.canonical({k: v for k, v in changed.items() if k != 'sha256'}))
            with self.assertRaises(h.Refused):
                h.validate_plan(changed, changed['sha256'])
        for field, value in (('source', '/etc/hosts'), ('destination', '/etc/hosts')):
            changed = copy.deepcopy(plan)
            changed['services'][0][field] = value
            changed['sha256'] = h.digest(h.canonical({k: v for k, v in changed.items() if k != 'sha256'}))
            with self.assertRaisesRegex(h.Refused, 'paths'):
                h.validate_plan(changed, changed['sha256'])
        changed = copy.deepcopy(plan)
        changed['services'][0]['domains'][0]['domain'] = 'system'
        changed['sha256'] = h.digest(h.canonical({k: v for k, v in changed.items() if k != 'sha256'}))
        with self.assertRaisesRegex(h.Refused, 'domain'):
            h.validate_plan(changed, changed['sha256'])

    def test_source_and_critical_file_drift_prevent_all_mutation(self):
        for path in (self.source, self.config, self.script, self.exe):
            original = path.read_bytes()
            plan = self.plan()
            path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(h.Refused, 'drifted'):
                h.apply(plan, plan['sha256'])
            self.assertFalse(self.commands)
            self.assertFalse((h.BACKUPS / plan['sha256']).exists())
            path.write_bytes(original)

    def test_forged_generated_plist_is_not_trusted_even_with_recomputed_digest(self):
        plan = self.plan()
        plan['services'][0]['plist']['UserName'] = 'root'
        plan['sha256'] = h.digest(h.canonical({k: v for k, v in plan.items() if k != 'sha256'}))
        with self.assertRaisesRegex(h.Refused, 'differs'):
            h.apply(plan, plan['sha256'])
        self.assertFalse(self.commands)

    def test_duplicate_domains_existing_daemon_and_missing_coordinator_refused(self):
        self.live.add(('user/' + str(os.getuid()), self.label))
        with self.assertRaisesRegex(h.Refused, 'Duplicate'):
            self.plan()
        self.live.remove(('user/' + str(os.getuid()), self.label))
        (self.daemons / (self.label + '.plist')).write_bytes(b'unrelated')
        with self.assertRaisesRegex(h.Refused, 'already exists'):
            self.plan()
        (self.daemons / (self.label + '.plist')).unlink()
        with self.assertRaisesRegex(h.Refused, 'coordinator'):
            self.plan('com.snowgloves.hermes-pilot.worker')

    def test_apply_backs_up_originals_and_db_before_stop_then_restores(self):
        original = self.source.read_bytes()
        plan = self.plan()
        normal_run = h.run
        def asserted_run(command, **kw):
            backup = h.BACKUPS / plan['sha256']
            self.assertEqual((backup / (self.label + '.agent.plist')).read_bytes(), original)
            self.assertTrue((backup / 'coordinator.sqlite3').exists())
            self.assertEqual(json.loads((backup / 'plan.json').read_bytes()), plan)
            return normal_run(command, **kw)
        with patch.object(h, 'run', asserted_run):
            result = h.apply(plan, plan['sha256'])
        self.assertFalse(result['cold_boot_verified'])
        self.assertFalse(self.source.exists())
        self.assertIn(('system', self.label), self.live)
        self.assertTrue(h.status(plan, plan['sha256'])['startup_candidate'])
        result = h.rollback(plan, plan['sha256'])
        self.assertFalse(result['database_restored'])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse((self.daemons / (self.label + '.plist')).exists())
        self.assertIn(('gui/' + str(os.getuid()), self.label), self.live)
        self.assertNotIn(('system', self.label), self.live)

    def test_apply_failure_leaves_recoverable_write_ahead_journal(self):
        plan = self.plan()
        self.bootstrap_error = True
        with self.assertRaisesRegex(h.Refused, 'roll back'):
            h.apply(plan, plan['sha256'])
        journal = json.loads((h.BACKUPS / plan['sha256'] / 'journal.json').read_bytes())
        self.assertEqual(journal['phase'], 'rollback-required')
        self.assertEqual(journal['installed'], [self.label])
        self.assertEqual(journal['failure'], {'operation': 'install-system-service',
                                             'service': self.label, 'kind': 'Refused'})
        self.bootstrap_error = False
        h.rollback(plan, plan['sha256'])
        self.assertTrue(self.source.exists())

    def test_stop_waits_for_launchd_with_a_bounded_command(self):
        with patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 0)) as command:
            with patch.object(h, 'loaded', return_value=False):
                h.stop_service('gui/501', self.label)
        command.assert_called_once_with(['/bin/launchctl', 'bootout', '--wait',
                                         'gui/501/' + self.label], timeout=25)
        with patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with patch.object(h, 'loaded', return_value=True):
                with self.assertRaisesRegex(h.Refused, 'remains loaded'):
                    h.stop_service('gui/501', self.label)

    def test_disabled_parser_accepts_observed_macos_state_words(self):
        original_disabled = ORIGINAL_DISABLED
        for state, expected in [('disabled', True), ('enabled', False), ('true', True), ('false', False)]:
            with self.subTest(state=state):
                output = ('disabled services = {\n "' + self.label + '" => ' + state + '\n}\n').encode()
                with patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 0, output, b'')):
                    self.assertEqual(original_disabled('gui/501', self.label), expected)
        with patch.object(h, 'run', return_value=subprocess.CompletedProcess([], 0,
                ('"' + self.label + '" => unknown').encode(), b'')):
            with self.assertRaisesRegex(h.Refused, 'Unrecognized'):
                original_disabled('gui/501', self.label)

    def test_rollback_preserves_newer_operator_edits(self):
        plan = self.plan()
        h.apply(plan, plan['sha256'])
        target = self.daemons / (self.label + '.plist')
        target.write_bytes(b'NEW_OPERATOR_CHANGE')
        before = len(self.commands)
        with self.assertRaisesRegex(h.Refused, 'drifted'):
            h.rollback(plan, plan['sha256'])
        self.assertEqual(target.read_bytes(), b'NEW_OPERATOR_CHANGE')
        self.assertEqual(len(self.commands), before)

    def test_quiescence_state_drift_prevents_mutations(self):
        plan = self.plan()
        self.probe['state_sha256'] = 'b' * 64
        with self.assertRaisesRegex(h.Refused, 'state changed'):
            h.apply(plan, plan['sha256'])
        self.assertFalse(self.commands)

    def test_real_sqlite_probe_refuses_queued_and_running_and_cancel_requested(self):
        for status in ('queued', 'running', 'cancel_requested'):
            with closing(sqlite3.connect(self.db)) as conn:
                conn.execute('DELETE FROM tasks')
                conn.execute('INSERT INTO tasks(id,status,updated) VALUES(?,?,?)', ('one', status, 1))
                conn.commit()
            with self.assertRaisesRegex(h.Refused, 'pending'):
                self.original_db_state({'db': str(self.db)}, self.info)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("UPDATE tasks SET status='succeeded'")
            conn.commit()
        state = self.original_db_state({'db': str(self.db)}, self.info)
        self.assertEqual(state['pending'], 0)
        self.assertEqual(len(state['state_sha256']), 64)

    def test_remote_probe_is_fixed_readonly_and_demoted_and_requires_stopped_scheduler(self):
        seen = []
        def ssh(command, **kw):
            seen.append((command, kw))
            return subprocess.CompletedProcess(command, 0, json.dumps(dict(self.probe, scheduler_loaded=True)).encode(), b'')
        with patch.object(h, 'run', ssh):
            with self.assertRaisesRegex(h.Refused, 'Stop the coordinator'):
                self.original_db_state({'db': str(self.db), 'ssh_host': 'axio@100.117.187.123', 'identity_file': str(self.config)}, self.info, require_stopped=True)
        self.assertEqual(seen[0][0][0], '/usr/bin/ssh')
        self.assertIn('IdentityAgent=none', seen[0][0])
        self.assertIn('StrictHostKeyChecking=yes', seen[0][0])
        self.assertEqual(seen[0][1]['info'], self.info)
        self.assertIn('mode=ro', seen[0][0][-1])
        with self.assertRaisesRegex(h.Refused, 'Unreviewed'):
            self.original_db_state({'db': str(self.db), 'ssh_host': 'attacker@example.org'}, self.info)

    def test_filevault_on_never_reports_startup_candidate_or_physical_proof(self):
        plan = self.plan()
        h.apply(plan, plan['sha256'])
        with patch.object(h, 'filevault', lambda: 'on-or-unknown'):
            result = h.status(plan, plan['sha256'])
        self.assertFalse(result['startup_candidate'])
        self.assertFalse(result['cold_boot_verified'])

    def test_cli_errors_never_echo_config_tokens_or_raw_exception(self):
        with patch.object(h, 'make_plan', side_effect=OSError('PRIVATE_TOKEN_CONTENT')):
            output = io.StringIO()
            with patch('sys.stderr', output):
                result = h.main(['inspect', '--user', 'axio', '--service', self.label, '--quiescence-db', str(self.db)])
        self.assertEqual(result, 2)
        self.assertNotIn('PRIVATE_TOKEN_CONTENT', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['ok'], False)


if __name__ == '__main__':
    unittest.main()


def test_gui_guard_distinguishes_python_app_property_from_bundle_path():
    assert not h.GUI.search("self.app, self.token = app, token\nreturn self.app(scope)")
    assert h.GUI.search("/Applications/Grok Bot.app/Contents/MacOS/Grok Bot")
    assert h.GUI.search('exec "/Applications/Grok Bot.app"')

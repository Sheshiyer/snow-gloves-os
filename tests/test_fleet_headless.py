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
ORIGINAL_USER_INFO = h.user_info
EXAMPLE_POLICY = Path(__file__).resolve().parents[1] / 'docs/fleet/headless-policy.example.json'
USER = 'operator'
REMOTE = 'operator@coordinator.example.ts.net'


class Headless(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.root = Path(self.tmp).resolve()
        self.home = self.root / USER
        self.home.mkdir(mode=0o700)
        self.agents = self.home / 'Library/LaunchAgents'
        self.agents.mkdir(parents=True, mode=0o700)
        self.logs = self.home / 'logs'
        self.logs.mkdir(mode=0o700)
        self.daemons = self.root / 'daemons'
        self.daemons.mkdir(mode=0o755)
        self.info = {'name': USER, 'uid': os.getuid(), 'gid': os.getgid(), 'home': str(self.home)}
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
        self.original_private_file = h.private_file
        self.original_write = h.write_private
        self.original_db_state = h.database_state
        self.stack.enter_context(patch.object(h, 'DAEMONS', self.daemons))
        self.stack.enter_context(patch.object(h, 'BACKUPS', self.root / 'backups'))
        self.stack.enter_context(patch.object(h.platform, 'system', lambda: 'Darwin'))
        self.stack.enter_context(patch.object(h.platform, 'node', lambda: 'coding01-test'))
        self.stack.enter_context(patch.object(h, 'user_info', self.fake_user_info))
        self.stack.enter_context(patch.object(h, 'account', self.fake_account))
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
        self.worker = 'com.snowgloves.hermes-pilot.worker'
        self.source = self.make_agent(self.label)
        self.live.add(('gui/' + str(os.getuid()), self.label))
        self.policy_doc = {'schema': h.POLICY_SCHEMA, 'users': {USER: {
            'labels': [self.label, self.worker, 'com.snowgloves.hermes-pilot.tls-renew'],
            'process_type': {self.worker: 'Standard'},
            'quiescence': {'db_root': str(self.home), 'ssh_hosts': [], 'requires_ssh_probe': False}}}}
        self.policy = self.write_policy(self.policy_doc)
        self.entry = h.user_policy(h.validate_policy(self.policy_doc), self.info)

    def fake_user_info(self, name, policy):
        self.assertIsInstance(policy, dict)
        if name not in policy['users']:
            raise h.Refused('Service user is not in the headless policy')
        return dict(self.info)

    def fake_account(self, name):
        if name != USER:
            raise h.Refused('Service user account does not exist')
        return dict(self.info)

    def owned_as(self, stack, uid, overrides=None):
        """Report every test file as owned by uid (per-file overrides) without real chown or root."""
        real = {name: getattr(os, name) for name in ('stat', 'lstat', 'fstat')}
        owners = {}
        for top, dirs, files in os.walk(self.root):
            for item in [top, *(os.path.join(top, n) for n in dirs + files)]:
                st = real['lstat'](item)
                owners[(st.st_dev, st.st_ino)] = uid
        for item, owner in (overrides or {}).items():
            st = real['lstat'](item)
            owners[(st.st_dev, st.st_ino)] = owner
        def remap(original):
            def wrapper(*args, **kw):
                st = original(*args, **kw)
                owner = owners.get((st.st_dev, st.st_ino))
                return st if owner is None else os.stat_result((*st[:4], owner, *st[5:10]))
            return wrapper
        for name, original in real.items():
            stack.enter_context(patch.object(os, name, remap(original)))

    def write_policy(self, doc, name='policy.json'):
        path = self.root / name
        path.write_text(json.dumps(doc))
        path.chmod(0o600)
        return path

    def render(self, source=None, entry=None):
        return h.render(source or self.source, self.info, entry or self.entry)

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
                    self.assertEqual(raw['UserName'], USER)
                self.live.add((command[2], raw['Label']))
        return subprocess.CompletedProcess(command, 0, b'', b'')

    def plan(self, *labels, policy=None):
        return h.make_plan(USER, list(labels or (self.label,)), str(self.db), policy=str(policy or self.policy))

    def test_nonroot_absolute_private_generated_service(self):
        generated, files = self.render()
        self.assertEqual(generated['UserName'], USER)
        self.assertEqual(generated['EnvironmentVariables']['HOME'], str(self.home))
        self.assertEqual(generated['EnvironmentVariables']['USER'], USER)
        self.assertEqual(generated['ProcessType'], 'Background')
        self.assertGreaterEqual(generated['ThrottleInterval'], 30)
        self.assertEqual(generated['Umask'], 0o077)
        self.assertIn(str(self.config), files)
        self.assertNotIn('PRIVATE_CONFIG_CONTENT', json.dumps(generated))
        self.assertNotIn('PRIVATE_CONFIG_CONTENT', json.dumps(files))

    def test_scheduled_renewal_does_not_become_continuous(self):
        label = 'com.snowgloves.hermes-pilot.tls-renew'
        source = self.make_agent(label, StartCalendarInterval={'Hour': 3, 'Minute': 12}, KeepAlive=False, RunAtLoad=False)
        generated, _ = self.render(source)
        self.assertFalse(generated['KeepAlive'])
        self.assertFalse(generated['RunAtLoad'])
        self.assertEqual(generated['StartCalendarInterval'], {'Hour': 3, 'Minute': 12})

    def test_module_carries_no_fleet_identities_and_example_policy_is_valid(self):
        for name in ('USERS', 'SERVICES', 'SSH_HOSTS'):
            self.assertFalse(hasattr(h, name))
        example = h.validate_policy(json.loads(EXAMPLE_POLICY.read_text()))
        self.assertIn('operator', example['users'])
        self.assertTrue(any(q['quiescence']['requires_ssh_probe'] for q in example['users'].values()))

    def test_env_node_entrypoint_gets_explicit_hashed_interpreter(self):
        node = self.home / 'node'
        node.write_text('#!/bin/sh\nexit 0\n')
        node.chmod(0o700)
        self.exe.write_text('#!/usr/bin/env node\n// fixture entrypoint\n')
        original = h.executable_path
        with patch.object(h, 'executable_path', lambda value, home: node if value == '/opt/homebrew/bin/node' else original(value, home)):
            generated, files = self.render()
        self.assertEqual(generated['ProgramArguments'][:2], [str(node), str(self.exe)])
        self.assertIn(str(node), files)
        self.exe.write_text('#!/usr/bin/env python3\n')
        with self.assertRaisesRegex(h.Refused, 'explicit interpreter'):
            self.render()

    def test_inline_secrets_and_interactive_dependencies_refused_without_echo(self):
        for env in ({'API_TOKEN': 'VERY_SECRET'}, {'HOME': '/Users/root'}, {'PATH': '.:/usr/bin'},
                    {'SSH_AUTH_SOCK': '/tmp/session.sock'}, {'NOTE': 'BEGIN RSA PRIVATE' + ' KEY'}):
            with self.subTest(env=tuple(env)):
                self.make_agent(self.label, EnvironmentVariables=env)
                with self.assertRaises(h.Refused) as caught:
                    self.render()
                self.assertNotIn('VERY_SECRET', str(caught.exception))

    def test_token_file_allowed_but_unsafe_mode_refused(self):
        token = self.home / 'app.token'
        token.write_text('PRIVATE_TOKEN_CONTENT')
        token.chmod(0o600)
        self.make_agent(self.label, EnvironmentVariables={'APP_TOKEN_FILE': str(token)})
        generated, files = self.render()
        self.assertIn(str(token), files)
        self.assertNotIn('PRIVATE_TOKEN_CONTENT', json.dumps(generated))
        token.chmod(0o644)
        with self.assertRaisesRegex(h.Refused, 'permissions'):
            self.render()

    def test_gui_labels_properties_args_and_wrappers_refused(self):
        for change in ({'Label': 'com.grok.app'}, {'LimitLoadToSessionType': 'Aqua'},
                       {'ProgramArguments': ['/usr/bin/open', '/Applications/Grok.app']},
                       {'ProcessType': 'Interactive'}, {'KeepAlive': {'SuccessfulExit': False}}):
            with self.subTest(change=tuple(change)):
                self.make_agent(self.label, **change)
                with self.assertRaises(h.Refused):
                    self.render()
        self.make_agent(self.label)
        self.script.write_text('import subprocess\nsubprocess.run(["osascript"])\n')
        with self.assertRaisesRegex(h.Refused, 'Wrapper'):
            self.render()

    def test_source_log_config_symlinks_and_traversal_refused(self):
        for value in ('relative.plist', str(self.home) + '/../outside', str(self.home) + '//logs/file'):
            with self.assertRaises(h.Refused):
                h.path_checked(value, self.home)
        alias = self.home / 'alias'
        alias.symlink_to(self.logs, target_is_directory=True)
        self.make_agent(self.label, StandardOutPath=str(alias / 'output.log'))
        with self.assertRaisesRegex(h.Refused, 'Symlink'):
            self.render()
        self.make_agent(self.label)
        self.config.chmod(0o644)
        with self.assertRaisesRegex(h.Refused, 'permissions'):
            self.render()

    def test_missing_config_and_private_log_bounds_refused(self):
        self.make_agent(self.label, ProgramArguments=[str(self.exe), '--config', str(self.home / 'missing.json')])
        with self.assertRaisesRegex(h.Refused, 'missing'):
            self.render()
        self.make_agent(self.label)
        self.logs.chmod(0o755)
        with self.assertRaisesRegex(h.Refused, 'private'):
            self.render()

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
                h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
            self.assertFalse(self.commands)
            self.assertFalse((h.BACKUPS / plan['sha256']).exists())
            path.write_bytes(original)

    def test_forged_generated_plist_is_not_trusted_even_with_recomputed_digest(self):
        plan = self.plan()
        plan['services'][0]['plist']['UserName'] = 'root'
        plan['sha256'] = h.digest(h.canonical({k: v for k, v in plan.items() if k != 'sha256'}))
        with self.assertRaisesRegex(h.Refused, 'differs'):
            h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
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
            result = h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
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
            h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
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
        h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
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
            h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
        self.assertFalse(self.commands)

    def test_real_sqlite_probe_refuses_queued_and_running_and_cancel_requested(self):
        for status in ('queued', 'running', 'cancel_requested'):
            with closing(sqlite3.connect(self.db)) as conn:
                conn.execute('DELETE FROM tasks')
                conn.execute('INSERT INTO tasks(id,status,updated) VALUES(?,?,?)', ('one', status, 1))
                conn.commit()
            with self.assertRaisesRegex(h.Refused, 'pending'):
                self.original_db_state({'db': str(self.db)}, self.info, self.entry['quiescence'])
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("UPDATE tasks SET status='succeeded'")
            conn.commit()
        state = self.original_db_state({'db': str(self.db)}, self.info, self.entry['quiescence'])
        self.assertEqual(state['pending'], 0)
        self.assertEqual(len(state['state_sha256']), 64)

    def test_remote_probe_is_fixed_readonly_and_demoted_and_requires_stopped_scheduler(self):
        seen = []
        def ssh(command, **kw):
            seen.append((command, kw))
            return subprocess.CompletedProcess(command, 0, json.dumps(dict(self.probe, scheduler_loaded=True)).encode(), b'')
        remote = {'db_root': str(self.home), 'ssh_hosts': [REMOTE], 'requires_ssh_probe': True}
        with patch.object(h, 'run', ssh):
            with self.assertRaisesRegex(h.Refused, 'Stop the coordinator'):
                self.original_db_state({'db': str(self.db), 'ssh_host': REMOTE, 'identity_file': str(self.config)}, self.info, remote, require_stopped=True)
        self.assertEqual(seen[0][0][0], '/usr/bin/ssh')
        self.assertIn('IdentityAgent=none', seen[0][0])
        self.assertIn('StrictHostKeyChecking=yes', seen[0][0])
        self.assertEqual(seen[0][1]['info'], self.info)
        self.assertIn('mode=ro', seen[0][0][-1])
        with self.assertRaisesRegex(h.Refused, 'Unreviewed'):
            self.original_db_state({'db': str(self.db), 'ssh_host': 'attacker@example.org'}, self.info, remote)
        with self.assertRaisesRegex(h.Refused, 'Unreviewed'):
            self.original_db_state({'db': str(self.db), 'ssh_host': REMOTE}, self.info, self.entry['quiescence'])
        with self.assertRaisesRegex(h.Refused, 'requires the coordinator SSH'):
            self.original_db_state({'db': str(self.db)}, self.info, remote)

    def test_filevault_on_never_reports_startup_candidate_or_physical_proof(self):
        plan = self.plan()
        h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
        with patch.object(h, 'filevault', lambda: 'on-or-unknown'):
            result = h.status(plan, plan['sha256'])
        self.assertFalse(result['startup_candidate'])
        self.assertFalse(result['cold_boot_verified'])

    def test_cli_errors_never_echo_config_tokens_or_raw_exception(self):
        with patch.object(h, 'make_plan', side_effect=OSError('PRIVATE_TOKEN_CONTENT')):
            output = io.StringIO()
            with patch('sys.stderr', output):
                result = h.main(['inspect', '--policy', str(self.policy), '--user', USER, '--service', self.label, '--quiescence-db', str(self.db)])
        self.assertEqual(result, 2)
        self.assertNotIn('PRIVATE_TOKEN_CONTENT', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['ok'], False)


    # --- private policy -------------------------------------------------

    def refused(self, doc, pattern=None):
        with self.assertRaises(h.Refused) as caught:
            h.validate_policy(doc)
        if pattern:
            self.assertRegex(str(caught.exception), pattern)

    def mutated(self, change):
        doc = copy.deepcopy(self.policy_doc)
        change(doc, doc['users'][USER])
        return doc

    def test_policy_validation_refuses_each_invalid_shape(self):
        q = lambda e: e['quiescence']
        cases = {
            'unknown top-level key': lambda d, e: d.update(extra=1),
            'wrong schema': lambda d, e: d.update(schema='snowgloves.headless-policy.v0'),
            'no users': lambda d, e: d.update(users={}),
            'root user': lambda d, e: d['users'].update(root=d['users'].pop(USER)),
            'invalid user name': lambda d, e: d['users'].update({'Bad User': d['users'].pop(USER)}),
            'unknown user key': lambda d, e: e.update(nice=5),
            'missing labels': lambda d, e: e.pop('labels'),
            'missing quiescence': lambda d, e: e.pop('quiescence'),
            'empty labels': lambda d, e: e.update(labels=[]),
            'duplicate labels': lambda d, e: e['labels'].append(self.label),
            'non-string label': lambda d, e: e['labels'].append(7),
            'path-like label': lambda d, e: e['labels'].append('../evil'),
            'apple label': lambda d, e: e['labels'].append('com.apple.screensharing'),
            'process type unlisted label': lambda d, e: e['process_type'].update({'com.example.other': 'Standard'}),
            'process type interactive': lambda d, e: e['process_type'].update({self.worker: 'Interactive'}),
            'process type adaptive': lambda d, e: e['process_type'].update({self.worker: 'Adaptive'}),
            'process type not a dict': lambda d, e: e.update(process_type=['Standard']),
            'working directory unlisted label': lambda d, e: e.update(working_directory={'com.example.other': str(self.home)}),
            'working directory relative': lambda d, e: e.update(working_directory={self.worker: 'relative/dir'}),
            'working directory traversal': lambda d, e: e.update(working_directory={self.worker: str(self.home) + '/../x'}),
            'unknown quiescence key': lambda d, e: q(e).update(port=22),
            'missing quiescence key': lambda d, e: q(e).pop('ssh_hosts'),
            'relative db root': lambda d, e: q(e).update(db_root='data'),
            'non-bool probe flag': lambda d, e: q(e).update(requires_ssh_probe='no'),
            'hosts without probe': lambda d, e: q(e).update(ssh_hosts=[REMOTE]),
            'probe without hosts': lambda d, e: q(e).update(requires_ssh_probe=True),
            'option-injection host': lambda d, e: q(e).update(ssh_hosts=['-oProxyCommand=x'], requires_ssh_probe=True),
            'host without user': lambda d, e: q(e).update(ssh_hosts=['coordinator.example.ts.net'], requires_ssh_probe=True),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.refused(self.mutated(change))
        for data, pattern in ((b'{"schema": 1, "schema": 2}', 'Duplicate'), (b'{"a": NaN}', 'Non-finite'),
                              (b'{not json', 'not valid JSON'), (b'\xff', 'not valid JSON')):
            with self.subTest(data=data):
                with self.assertRaisesRegex(h.Refused, pattern):
                    h.strict_json(data)
        outside = self.mutated(lambda d, e: e.update(working_directory={self.worker: str(self.root / 'elsewhere')}))
        with self.assertRaisesRegex(h.Refused, 'outside the service home'):
            h.user_policy(h.validate_policy(outside), self.info)
        remote_db = self.mutated(lambda d, e: e['quiescence'].update(db_root=str(self.root / 'other')))
        with self.assertRaisesRegex(h.Refused, 'inside the service home'):
            h.user_policy(h.validate_policy(remote_db), self.info)
        with self.assertRaisesRegex(h.Refused, 'not in the headless policy'):
            h.user_policy(h.validate_policy(self.policy_doc), dict(self.info, name='someone'))

    def test_policy_file_must_be_private_regular_owned_and_present(self):
        self.policy.chmod(0o644)
        with self.assertRaisesRegex(h.Refused, 'private'):
            h.read_policy(str(self.policy))
        with self.assertRaisesRegex(h.Refused, 'private'):
            self.plan()
        self.policy.chmod(0o600)
        with self.assertRaisesRegex(h.Refused, 'owned'):
            h.read_policy(str(self.policy), owners={os.getuid() + 1})
        alias = self.root / 'alias.json'
        alias.symlink_to(self.policy)
        with self.assertRaisesRegex(h.Refused, 'Symlink'):
            h.read_policy(str(alias))
        with self.assertRaisesRegex(h.Refused, 'missing'):
            h.read_policy(str(self.root / 'absent.json'))
        policy, source = h.read_policy(str(self.policy))
        self.assertEqual(policy, h.validate_policy(self.policy_doc))
        self.assertEqual(source['sha256'], h.digest(self.policy.read_bytes()))
        self.assertEqual(source['mode'], 0o600)

    def test_root_run_plan_accepts_service_user_owned_policy_only(self):
        service = 60001 if os.getuid() != 60001 else 60002
        stranger = service + 1
        self.info = dict(self.info, uid=service)
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, 'geteuid', lambda: 0))
            self.owned_as(stack, service)
            plan = self.plan()
        self.assertEqual(plan['policy_source']['uid'], service)
        self.assertEqual(plan['user']['uid'], service)
        self.assertEqual(plan['policy'], h.validate_policy(self.policy_doc))
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, 'geteuid', lambda: 0))
            self.owned_as(stack, service, {self.policy: 0})
            self.assertEqual(self.plan()['policy_source']['uid'], 0)
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, 'geteuid', lambda: 0))
            self.owned_as(stack, service, {self.policy: stranger})
            with self.assertRaisesRegex(h.Refused, 'owned by the service user or root'):
                self.plan()
        self.policy.chmod(0o640)
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, 'geteuid', lambda: 0))
            self.owned_as(stack, service)
            with self.assertRaisesRegex(h.Refused, 'private'):
                self.plan()
        self.policy.chmod(0o600)
        opened = []
        real_open = os.open
        with ExitStack() as stack:
            stack.enter_context(patch.object(os, 'geteuid', lambda: stranger))
            stack.enter_context(patch.object(os, 'open', lambda *a, **kw: opened.append(a[0]) or real_open(*a, **kw)))
            self.owned_as(stack, stranger)
            with self.assertRaisesRegex(h.Refused, 'selected service user or root'):
                self.plan()
        self.assertNotIn(self.policy, [Path(x) for x in opened])

    def test_plan_refused_without_policy_with_clear_reason(self):
        with self.assertRaisesRegex(h.Refused, 'policy is required; pass --policy'):
            h.make_plan(USER, [self.label], str(self.db))
        output = io.StringIO()
        with patch('sys.stderr', output):
            result = h.main(['plan', '--user', USER, '--service', self.label, '--quiescence-db', str(self.db),
                             '--output', str(self.home / 'plan.json')])
        self.assertEqual(result, 2)
        self.assertIn('--policy', json.loads(output.getvalue())['reason'])
        self.assertFalse((self.home / 'plan.json').exists())
        other = self.write_policy(dict(self.policy_doc, users={'someone': self.policy_doc['users'][USER]}), 'other.json')
        with self.assertRaisesRegex(h.Refused, 'not in the headless policy'):
            self.plan(policy=other)

    def test_process_type_defaults_background_and_standard_needs_policy(self):
        generated, _ = self.render()
        self.assertEqual(generated['ProcessType'], 'Background')
        worker = self.make_agent(self.worker)
        self.assertEqual(self.render(worker)[0]['ProcessType'], 'Standard')
        worker = self.make_agent(self.worker, ProcessType='Background')
        self.assertEqual(self.render(worker)[0]['ProcessType'], 'Standard')
        worker = self.make_agent(self.worker, ProcessType='Standard')
        self.assertEqual(self.render(worker)[0]['ProcessType'], 'Standard')
        self.make_agent(self.label, ProcessType='Standard')
        with self.assertRaisesRegex(h.Refused, 'Standard source process type'):
            self.render()
        for kind in ('Interactive', 'Adaptive'):
            with self.subTest(kind=kind):
                worker = self.make_agent(self.worker, ProcessType=kind)
                with self.assertRaisesRegex(h.Refused, 'GUI process type'):
                    self.render(worker)

    def test_working_directory_override_valid_outside_symlink_missing_and_writable(self):
        checkout = self.home / 'checkout'
        checkout.mkdir(mode=0o700)
        worker = self.make_agent(self.worker, WorkingDirectory=str(self.home))
        entry = copy.deepcopy(self.entry)
        entry['working_directory'] = {self.worker: str(checkout)}
        generated, _ = self.render(worker, entry)
        self.assertEqual(generated['WorkingDirectory'], str(checkout))
        # Normal checkouts (0755) and home-like directories (0750) are accepted.
        for mode in (0o755, 0o750, 0o700, 0o555):
            with self.subTest(accepted=oct(mode)):
                checkout.chmod(mode)
                self.assertEqual(self.render(worker, entry)[0]['WorkingDirectory'], str(checkout))
        checkout.chmod(0o755)
        outside = self.root / 'outside'
        outside.mkdir(mode=0o700)
        alias = self.home / 'alias'
        alias.symlink_to(outside, target_is_directory=True)
        inner_alias = self.home / 'inner-alias'
        inner_alias.symlink_to(checkout, target_is_directory=True)
        group_writable = self.home / 'group-writable'
        group_writable.mkdir()
        group_writable.chmod(0o775)
        world_writable = self.home / 'world-writable'
        world_writable.mkdir()
        world_writable.chmod(0o777)
        sticky_world = self.home / 'sticky-world'
        sticky_world.mkdir()
        sticky_world.chmod(0o1777)
        for value, pattern in ((str(outside), 'outside the service home'), (str(alias), 'Symlink'),
                               (str(alias / 'nested'), 'Symlink'), (str(inner_alias), 'Symlink'),
                               (str(self.home / 'missing'), 'already exist'),
                               (str(group_writable), 'group- or other-writable'),
                               (str(world_writable), 'group- or other-writable'),
                               (str(sticky_world), 'group- or other-writable'),
                               ('relative/dir', 'absolute')):
            with self.subTest(refused=value):
                entry['working_directory'] = {self.worker: value}
                with self.assertRaisesRegex(h.Refused, pattern) as caught:
                    self.render(worker, entry)
                self.assertIn('policy working directory for ' + self.worker, str(caught.exception))
        entry['working_directory'] = {self.worker: str(checkout)}
        stranger = os.getuid() + 1
        with ExitStack() as stack:
            self.owned_as(stack, os.getuid(), {checkout: stranger})
            with self.assertRaisesRegex(h.Refused, 'owned by the service user or root'):
                self.render(worker, entry)
        with ExitStack() as stack:
            self.owned_as(stack, os.getuid(), {checkout: 0})
            self.assertEqual(self.render(worker, entry)[0]['WorkingDirectory'], str(checkout))
        doc = copy.deepcopy(self.policy_doc)
        renew = 'com.snowgloves.hermes-pilot.tls-renew'
        doc['users'][USER]['working_directory'] = {renew: str(self.home / 'missing')}
        # Overrides are validated for every label of the user, selected or not,
        # and the refusal names the label.
        with self.assertRaisesRegex(h.Refused, 'already exist.*policy working directory for ' + renew):
            self.plan(policy=self.write_policy(doc, 'missing-wd.json'))
        doc['users'][USER]['working_directory'] = {renew: str(group_writable)}
        with self.assertRaisesRegex(h.Refused, 'group- or other-writable.*' + renew):
            self.plan(policy=self.write_policy(doc, 'writable-wd.json'))
        doc['users'][USER]['working_directory'] = {self.worker: str(checkout)}
        self.make_agent(self.worker)
        plan = self.plan(self.label, self.worker, policy=self.write_policy(doc, 'wd.json'))
        planned = {s['label']: s['plist'] for s in plan['services']}
        self.assertEqual(planned[self.worker]['WorkingDirectory'], str(checkout))
        self.assertEqual(planned[self.worker]['ProcessType'], 'Standard')
        self.assertEqual(planned[self.label]['ProcessType'], 'Background')

    def test_log_directories_stay_private_while_working_directories_relax(self):
        self.logs.chmod(0o755)
        with self.assertRaisesRegex(h.Refused, 'private'):
            self.render()
        self.logs.chmod(0o750)
        with self.assertRaisesRegex(h.Refused, 'private'):
            self.render()

    def test_policy_is_embedded_fingerprinted_and_digest_bound(self):
        with patch.object(h.time, 'time', lambda: 1_700_000_000):
            first = self.plan()
            same = self.plan()
            doc = copy.deepcopy(self.policy_doc)
            doc['users'][USER]['process_type'] = {}
            changed = self.plan(policy=self.write_policy(doc, 'changed.json'))
        self.assertEqual(first['policy'], h.validate_policy(self.policy_doc))
        self.assertEqual(first['policy_source']['sha256'], h.digest(self.policy.read_bytes()))
        self.assertNotIn(str(self.policy), first['files'])
        self.assertEqual(first['sha256'], same['sha256'])
        self.assertNotEqual(first['sha256'], changed['sha256'])
        tampered = copy.deepcopy(first)
        tampered['policy']['users'][USER]['labels'].append('com.example.extra')
        with self.assertRaisesRegex(h.Refused, 'digest'):
            h.validate_plan(tampered, first['sha256'])

    def resign(self, plan):
        """Forge as the plan's writer could: recompute both embedded digests."""
        if 'policy' in plan and 'policy_sha256' in plan:
            plan['policy_sha256'] = h.digest(h.canonical(plan['policy']))
        plan['sha256'] = h.digest(h.canonical({k: v for k, v in plan.items() if k != 'sha256'}))
        return plan

    def test_embedded_policy_allowlists_are_enforced(self):
        self.make_agent(self.worker)
        plan = self.plan(self.label, self.worker)
        info, entry = h.validate_plan(plan, plan['sha256'])
        self.assertEqual(entry['process_type'], {self.worker: 'Standard'})
        narrowed = copy.deepcopy(plan)
        narrowed['policy']['users'][USER]['labels'].remove(self.worker)
        narrowed['policy']['users'][USER]['process_type'] = {}
        with self.assertRaisesRegex(h.Refused, 'Invalid selected services'):
            h.validate_plan(self.resign(narrowed), narrowed['sha256'])
        renamed = copy.deepcopy(plan)
        renamed['policy']['users'] = {'someone': renamed['policy']['users'][USER]}
        with self.assertRaisesRegex(h.Refused, 'not in the headless policy'):
            h.validate_plan(self.resign(renamed), renamed['sha256'])
        remote = copy.deepcopy(plan)
        remote['policy']['users'][USER]['labels'].remove(self.label)
        remote['services'] = [s for s in remote['services'] if s['label'] != self.label]
        with self.assertRaisesRegex(h.Refused, 'coordinator'):
            h.validate_plan(self.resign(remote), remote['sha256'])
        noncanonical = copy.deepcopy(plan)
        del noncanonical['policy']['users'][USER]['working_directory']
        with self.assertRaisesRegex(h.Refused, 'not canonical'):
            h.validate_plan(self.resign(noncanonical), noncanonical['sha256'])
        missing = copy.deepcopy(plan)
        del missing['policy']
        with self.assertRaisesRegex(h.Refused, 'policy schema'):
            h.validate_plan(self.resign(missing), missing['sha256'])
        downgraded = copy.deepcopy(plan)
        downgraded['policy']['users'][USER]['process_type'] = {}
        with self.assertRaisesRegex(h.Refused, 'differs'):
            h.apply(self.resign(downgraded), downgraded['sha256'], expected_policy=downgraded['policy_sha256'])
        self.assertFalse(self.commands)
        with self.assertRaisesRegex(h.Refused, 'coordinator'):
            self.plan(self.worker)
        with self.assertRaisesRegex(h.Refused, 'labels'):
            self.plan(self.label, 'com.example.unlisted')
        with self.assertRaisesRegex(h.Refused, 'SSH probe selection'):
            h.make_plan(USER, [self.label], str(self.db), REMOTE, policy=str(self.policy))

    def test_root_operations_never_open_a_policy_file(self):
        plan = self.plan()
        target = str(self.policy)
        self.policy.unlink()
        seen, calls = [], []
        def spy(original):
            def wrapper(*args, **kw):
                calls.append(1)
                if args and str(args[0]) == target:
                    seen.append(args[0])
                return original(*args, **kw)
            return wrapper
        with ExitStack() as stack:
            stack.enter_context(patch('builtins.open', spy(open)))
            stack.enter_context(patch.object(io, 'open', spy(io.open)))
            stack.enter_context(patch.object(os, 'open', spy(os.open)))
            for name in ('open', 'read_bytes', 'read_text'):
                stack.enter_context(patch.object(Path, name, spy(getattr(Path, name))))
            h.validate_plan(plan, plan['sha256'])
            h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
            self.assertTrue(h.status(plan, plan['sha256'])['startup_candidate'])
            h.rollback(plan, plan['sha256'])
        self.assertTrue(calls)
        self.assertEqual(seen, [])
        self.assertTrue(self.source.exists())

    # --- operator-pinned policy digest ------------------------------------

    def record_launchctl(self, stack):
        """Record every launchctl touch, including read-only print/print-disabled probes."""
        calls = []
        live, off = self.live, self.disabled
        stack.enter_context(patch.object(h, 'loaded', lambda d, l: calls.append(('print', d, l)) or (d, l) in live))
        stack.enter_context(patch.object(h, 'disabled', lambda d, l: calls.append(('print-disabled', d, l)) or (d, l) in off))
        stack.enter_context(patch.object(h, 'run', lambda command, **kw: calls.append(tuple(command)) or self.fake_run(command, **kw)))
        return calls

    def remote_plan(self):
        doc = copy.deepcopy(self.policy_doc)
        doc['users'][USER]['labels'] = [self.worker]
        doc['users'][USER]['quiescence'] = {'db_root': str(self.home), 'ssh_hosts': [REMOTE], 'requires_ssh_probe': True}
        self.make_agent(self.worker)
        return h.make_plan(USER, [self.worker], str(self.db), REMOTE, identity_file=str(self.config),
                           policy=str(self.write_policy(doc, 'remote.json')))

    def test_forged_embedded_policy_refused_before_any_launchctl_call(self):
        local, remote = self.plan(), self.remote_plan()
        def interactive(p):
            p['users'][USER]['process_type'][self.worker] = 'Interactive'
        def root_user(p):
            p['users']['root'] = p['users'].pop(USER)
        def apple_label(p):
            p['users'][USER]['labels'].append('com.apple.foo')
        def local_quiescence(p):
            p['users'][USER]['quiescence'] = {'db_root': str(self.home), 'ssh_hosts': [], 'requires_ssh_probe': False}
        cases = (('interactive', local, interactive), ('root user', local, root_user),
                 ('apple label', local, apple_label), ('ssh user switched to local db', remote, local_quiescence))
        for name, plan, change in cases:
            forged = copy.deepcopy(plan)
            change(forged['policy'])
            self.resign(forged)
            self.assertEqual(forged['policy_sha256'], h.digest(h.canonical(forged['policy'])))
            self.assertEqual(h.canonical(json.loads(h.canonical(forged))), h.canonical(forged))
            # Neither the operator's real digest nor the forger's own digest gets through.
            for expected_policy in (plan['policy_sha256'], forged['policy_sha256']):
                with self.subTest(name, expected_policy=expected_policy[:8]), ExitStack() as stack:
                    calls = self.record_launchctl(stack)
                    with self.assertRaises(h.Refused):
                        h.apply(forged, forged['sha256'], expected_policy=expected_policy)
                    self.assertEqual(calls, [])
                    self.assertFalse(h.BACKUPS.exists())
        # A well-formed policy swap (extra label, copied policy_source) is caught only
        # by the operator's digest: the forger can re-sign everything else.
        widened = copy.deepcopy(local)
        widened['policy']['users'][USER]['labels'].append('com.example.extra')
        self.resign(widened)
        self.assertEqual(widened['policy_source'], local['policy_source'])
        h.validate_plan(widened, widened['sha256'])
        with ExitStack() as stack:
            calls = self.record_launchctl(stack)
            with self.assertRaisesRegex(h.Refused, 'operator-reviewed policy digest'):
                h.apply(widened, widened['sha256'], expected_policy=local['policy_sha256'])
            self.assertEqual(calls, [])

    def test_apply_requires_matching_expect_policy_sha256(self):
        plan = self.plan()
        self.assertEqual(plan['policy_sha256'], h.policy_digest(self.policy_doc))
        with ExitStack() as stack:
            calls = self.record_launchctl(stack)
            for value, pattern in ((None, '--expect-policy-sha256'), ('', '--expect-policy-sha256'),
                                   (plan['policy_sha256'].upper(), '--expect-policy-sha256'),
                                   (plan['policy_sha256'][:63], '--expect-policy-sha256'),
                                   ('b' * 64, 'operator-reviewed policy digest'),
                                   (plan['sha256'], 'operator-reviewed policy digest')):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(h.Refused, pattern):
                        h.apply(plan, plan['sha256'], expected_policy=value)
            with self.assertRaisesRegex(h.Refused, '--expect-policy-sha256'):
                h.apply(plan, plan['sha256'])
            stored = copy.deepcopy(plan)
            stored['policy_sha256'] = 'c' * 64
            stored['sha256'] = h.digest(h.canonical({k: v for k, v in stored.items() if k != 'sha256'}))
            for operation in (h.apply, h.status, h.rollback):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(h.Refused, 'Embedded headless policy digest'):
                        operation(stored, stored['sha256'], expected_policy=plan['policy_sha256'])
            # Plans from the pre-hardening helper have no recorded digest: never applied.
            unrecorded = {k: v for k, v in plan.items() if k != 'policy_sha256'}
            self.resign(unrecorded)
            with self.assertRaisesRegex(h.Refused, 'Embedded headless policy digest'):
                h.apply(unrecorded, unrecorded['sha256'], expected_policy=plan['policy_sha256'])
            self.assertEqual(calls, [])
        self.assertFalse(h.BACKUPS.exists())
        self.assertEqual(h.status(unrecorded, unrecorded['sha256'])['policy_sha256'], plan['policy_sha256'])
        result = h.apply(plan, plan['sha256'], expected_policy=plan['policy_sha256'])
        self.assertEqual(result['policy_sha256'], plan['policy_sha256'])
        self.assertEqual(h.status(plan, plan['sha256'])['policy_sha256'], plan['policy_sha256'])
        self.assertTrue(h.status(plan, plan['sha256'], expected_policy=plan['policy_sha256'])['startup_candidate'])
        with self.assertRaisesRegex(h.Refused, 'operator-reviewed'):
            h.status(plan, plan['sha256'], expected_policy='b' * 64)
        before = len(self.commands)
        with self.assertRaisesRegex(h.Refused, 'operator-reviewed'):
            h.rollback(plan, plan['sha256'], expected_policy='b' * 64)
        self.assertEqual(len(self.commands), before)
        # Rollback is a recovery path: the policy digest is optional there, and printed.
        self.assertEqual(h.rollback(plan, plan['sha256'])['policy_sha256'], plan['policy_sha256'])

    def test_cli_apply_requires_policy_digest_flag_and_reports_digests(self):
        plan = self.plan()
        def cli(*args):
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(h, 'load_review', lambda path: copy.deepcopy(plan)), \
                    patch('sys.stdout', output), patch('sys.stderr', errors):
                code = h.main(list(args))
            return code, output.getvalue(), errors.getvalue()
        code, _out, err = cli('apply', '--plan', '/unused', '--expect-sha256', plan['sha256'])
        self.assertEqual(code, 2)
        self.assertIn('--expect-policy-sha256', json.loads(err)['reason'])
        code, _out, err = cli('apply', '--plan', '/unused', '--expect-sha256', plan['sha256'],
                              '--expect-policy-sha256', 'b' * 64)
        self.assertEqual(code, 2)
        self.assertIn('operator-reviewed', json.loads(err)['reason'])
        self.assertFalse(self.commands)
        code, out, _err = cli('apply', '--plan', '/unused', '--expect-sha256', plan['sha256'],
                              '--expect-policy-sha256', plan['policy_sha256'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['policy_sha256'], plan['policy_sha256'])
        code, out, _err = cli('status', '--plan', '/unused', '--expect-sha256', plan['sha256'])
        self.assertEqual((code, json.loads(out)['policy_sha256']), (0, plan['policy_sha256']))
        code, _out, err = cli('rollback', '--plan', '/unused', '--expect-sha256', plan['sha256'],
                              '--expect-policy-sha256', 'b' * 64)
        self.assertEqual(code, 2)
        code, out, _err = cli('rollback', '--plan', '/unused', '--expect-sha256', plan['sha256'],
                              '--expect-policy-sha256', plan['policy_sha256'])
        self.assertEqual((code, json.loads(out)['policy_sha256']), (0, plan['policy_sha256']))

    def policy_digest_cli(self, path):
        output, errors = io.StringIO(), io.StringIO()
        with patch('sys.stdout', output), patch('sys.stderr', errors):
            code = h.main(['policy-digest', '--policy', str(path)])
        return code, (json.loads(output.getvalue()) if code == 0 else json.loads(errors.getvalue()))

    def test_policy_digest_output_is_stable_canonical_and_matches_plans(self):
        pinned = {'schema': h.POLICY_SCHEMA, 'users': {'operator': {'labels': ['com.example.a'], 'quiescence': {
            'db_root': '/Users/operator', 'ssh_hosts': [], 'requires_ssh_probe': False}}}}
        canonical = (b'{"schema":"snowgloves.headless-policy.v1","users":{"operator":{"labels":["com.example.a"],'
                     b'"process_type":{},"quiescence":{"db_root":"/Users/operator","requires_ssh_probe":false,'
                     b'"ssh_hosts":[]},"working_directory":{}}}}')
        expected = '4026d9b4b588d5b0b690dd0aa4273369a8ded5dd3307781feffffc9ff159ac7c'
        self.assertEqual(h.canonical(h.validate_policy(pinned)), canonical)
        self.assertEqual(h.digest(canonical), expected)
        self.assertEqual(h.policy_digest(pinned), expected)
        self.assertEqual(self.policy_digest_cli(self.write_policy(pinned, 'pinned.json')), (0, {'ok': True, 'policy_sha256': expected}))
        # Formatting, key order and explicit empty optional maps do not change the digest.
        variant = self.root / 'variant.json'
        variant.write_text('{\n  "users": {"operator": {"working_directory": {}, "quiescence": {"requires_ssh_probe": false,'
                           ' "ssh_hosts": [], "db_root": "/Users/operator"}, "process_type": {},'
                           ' "labels": ["com.example.a"]}},\n  "schema": "snowgloves.headless-policy.v1"\n}\n')
        variant.chmod(0o644)
        self.assertEqual(self.policy_digest_cli(variant), (0, {'ok': True, 'policy_sha256': expected}))
        # Any semantic change (label, label order, quiescence) changes it.
        for change in (lambda e: e['labels'].append('com.example.b'),
                       lambda e: e.update(labels=['com.example.b']),
                       lambda e: e['quiescence'].update(db_root='/Users/operator/data')):
            doc = copy.deepcopy(pinned)
            change(doc['users']['operator'])
            self.assertNotEqual(h.policy_digest(doc), expected)
        # It equals the digest a plan embeds for the same file.
        code, result = self.policy_digest_cli(self.policy)
        self.assertEqual(code, 0)
        self.assertEqual(result['policy_sha256'], self.plan()['policy_sha256'])
        self.assertEqual(self.policy_digest_cli(EXAMPLE_POLICY)[0], 0)
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(self.policy_digest_cli('pinned.json'), (0, {'ok': True, 'policy_sha256': expected}))
        finally:
            os.chdir(cwd)
        # The reviewed copy may be readable but never writable by others, a symlink or invalid.
        for mode in (0o664, 0o646, 0o666):
            with self.subTest(mode=oct(mode)):
                variant.chmod(mode)
                code, result = self.policy_digest_cli(variant)
                self.assertEqual(code, 2)
                self.assertIn('writable', result['reason'])
        alias = self.root / 'alias-policy.json'
        alias.symlink_to(self.policy)
        self.assertIn('Symlink', self.policy_digest_cli(alias)[1]['reason'])
        bad = copy.deepcopy(pinned)
        bad['users']['operator']['process_type'] = {'com.example.a': 'Interactive'}
        code, result = self.policy_digest_cli(self.write_policy(bad, 'bad.json'))
        self.assertEqual(code, 2)
        self.assertNotIn('policy_sha256', result)

    def legacy(self):
        plan = self.plan()
        legacy = {k: v for k, v in plan.items() if k not in ('policy', 'policy_source', 'sha256')}
        legacy['schema'] = h.LEGACY_SCHEMA
        return self.resign(legacy)

    def test_legacy_plans_need_explicit_legacy_policy_for_rollback_and_status_only(self):
        legacy = self.legacy()
        policy = h.validate_policy(self.policy_doc)
        for operation in (h.status, h.rollback, h.apply):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(h.Refused, '--legacy-policy'):
                    operation(legacy, legacy['sha256'])
        self.assertFalse(h.status(legacy, legacy['sha256'], policy)['startup_candidate'])
        self.assertEqual(h.status(legacy, legacy['sha256'], policy, expected_policy=h.policy_digest(policy))['policy_sha256'],
                         h.policy_digest(policy))
        with self.assertRaisesRegex(h.Refused, 'operator-reviewed'):
            h.status(legacy, legacy['sha256'], policy, expected_policy='b' * 64)
        backup = h.backup_directory(legacy)
        h.save_journal(backup, {'schema': h.LEGACY_SCHEMA, 'phase': 'prepared', 'stopped': [], 'installed': []})
        self.assertTrue(h.rollback(legacy, legacy['sha256'], policy)['ok'])
        other = copy.deepcopy(self.policy_doc)
        other['users'][USER]['labels'] = [self.worker]
        with self.assertRaisesRegex(h.Refused, 'Invalid selected services'):
            h.status(legacy, legacy['sha256'], other)
        current = self.plan()
        with self.assertRaisesRegex(h.Refused, 'only to plans without'):
            h.status(current, current['sha256'], policy)
        with self.assertRaises(TypeError):
            h.apply(legacy, legacy['sha256'], policy)

    def test_cli_reads_legacy_policy_only_for_legacy_plans(self):
        legacy, current = self.legacy(), self.plan()
        absent = str(self.root / 'never-read.json')
        for plan in (current, legacy):
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(h, 'load_review', lambda path, plan=plan: copy.deepcopy(plan)), \
                    patch.object(h, 'plan_owners', lambda plan: {0, os.getuid()}), \
                    patch('sys.stdout', output), patch('sys.stderr', errors):
                h.main(['status', '--plan', '/unused', '--expect-sha256', plan['sha256'], '--legacy-policy', absent])
                code = h.main(['status', '--plan', '/unused', '--expect-sha256', plan['sha256'],
                               '--legacy-policy', str(self.policy)])
            if plan is current:
                self.assertEqual(code, 2)
                self.assertIn('only to plans without', errors.getvalue())
                self.assertNotIn('missing', errors.getvalue())
            else:
                self.assertEqual(code, 0)
                self.assertIn('missing', errors.getvalue())
                self.assertIn('startup_candidate', output.getvalue())


if __name__ == '__main__':
    unittest.main()


def test_gui_guard_distinguishes_python_app_property_from_bundle_path():
    assert not h.GUI.search("self.app, self.token = app, token\nreturn self.app(scope)")
    assert h.GUI.search("/Applications/Grok Bot.app/Contents/MacOS/Grok Bot")
    assert h.GUI.search('exec "/Applications/Grok Bot.app"')

import json
import subprocess
from unittest import mock
"""Tests for Supervisor: SQLite lifecycle, backup/restore, admission, fail-closed.

Test child is a clearly labelled test fixture — production always uses supplied real runtime.
"""

import os
import shutil
import signal
import sqlite3
import sys
from pathlib import Path
import tempfile
import threading
import time
import unittest

from lib.runtime_supervisor import Supervisor

TEST_SECRET = "test-management-secret-value-12345"
TEST_KEY = "test-storage-encryption-key-67890"


def _test_child_script(directory):
    """Return path to a test fixture child script that stays alive until signaled.

    The fixture reads DATA_DIR from env, uses an existing SQLite table, writes a row,
    then loops until interrupted. This is a TEST FIXTURE only.
    Production always uses the supplied real runtime.
    """
    path = os.path.join(directory, "child_fixture.py")
    with open(path, "w") as f:
        f.write(
            "import os, signal, sqlite3, sys, time\n"
            "data_dir = os.environ['DATA_DIR']\n"
            "assert os.environ['STORAGE_ENCRYPTION_KEY']\n"
            "db = os.path.join(data_dir, 'storage.sqlite')\n"
            "conn = sqlite3.connect(db)\n"
            "conn.execute('CREATE TABLE IF NOT EXISTS kv (k TEXT, v TEXT)')\n"
            "conn.execute(\"INSERT INTO kv VALUES ('child', 'alive')\")\n"
            "conn.commit(); conn.close()\n"
            "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
            "while True:\n"
            "    time.sleep(0.5)\n"
        )
    return path


class TestSupervisor(unittest.TestCase):
    """Unit tests for the Supervisor class."""

    def setUp(self):
        self._tmpdir = str(Path(tempfile.mkdtemp(prefix="sup_test_")).resolve())
        with sqlite3.connect(os.path.join(self._tmpdir, "storage.sqlite")) as db:
            db.execute("CREATE TABLE kv (k TEXT, v TEXT)")
        self._child_script = _test_child_script(self._tmpdir)
        self._supervisors = []

    def tearDown(self):
        for s in self._supervisors:
            try:
                s.shutdown()
            except Exception:
                pass
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        try:
            os.unlink(self._child_script)
        except OSError:
            pass

    def _mk(self, **kwargs):
        defaults = dict(
            data_dir=self._tmpdir,
            command=[sys.executable, "-S", self._child_script],
            storage_key=TEST_KEY,
            management_secret=TEST_SECRET,
            admission=True,
        )
        defaults.update(kwargs)
        s = Supervisor(**defaults)
        self._supervisors.append(s)
        return s

    # --- Constructor validation ---

    def test_constructor_requires_storage_key(self):
        with self.assertRaises(ValueError):
            Supervisor(self._tmpdir, ["echo"], "", TEST_SECRET)

    def test_constructor_requires_management_secret(self):
        with self.assertRaises(ValueError):
            Supervisor(self._tmpdir, ["echo"], TEST_KEY, "")

    def test_constructor_requires_data_dir(self):
        with self.assertRaises(ValueError):
            Supervisor("", ["echo"], TEST_KEY, TEST_SECRET)

    def test_constructor_requires_command(self):
        with self.assertRaises(ValueError):
            Supervisor(self._tmpdir, [], TEST_KEY, TEST_SECRET)

    def test_constructor_rejects_symlinked_data_dir(self):
        real = os.path.join(self._tmpdir, "real")
        link = os.path.join(self._tmpdir, "link")
        os.makedirs(real)
        os.symlink(real, link)
        with self.assertRaises(ValueError):
            Supervisor(link, ["echo"], TEST_KEY, TEST_SECRET)

    # --- Admission / readiness ---

    def test_no_admission_stays_unavailable(self):
        s = self._mk(admission=False)
        s.start()
        self.assertFalse(s.ready)

    def test_ready_when_child_alive_quickcheck_and_admission(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)

    def test_child_dies_stays_unavailable(self):
        """Child exits immediately before readiness gates complete."""
        # os._exit is near-instant; combined with 0.15s sleep in start(),
        # this should be reliably dead by the readiness check.
        s = self._mk(command=[sys.executable, "-S", "-c", "import os; os._exit(1)"])
        s.start()
        self.assertFalse(s.ready)

    # --- Symlinked DB ---

    def test_symlinked_db_rejected(self):
        os.makedirs(self._tmpdir, exist_ok=True)
        real_db = os.path.join(self._tmpdir, "real.sqlite")
        c = sqlite3.connect(real_db)
        c.execute("CREATE TABLE t (x)")
        c.close()
        os.unlink(os.path.join(self._tmpdir, "storage.sqlite"))
        os.symlink(real_db, os.path.join(self._tmpdir, "storage.sqlite"))
        s = self._mk()
        s.start()
        self.assertFalse(s.ready)

    # --- Missing / corrupt DB ---

    def test_missing_db_stays_absent_and_unavailable(self):
        os.unlink(os.path.join(self._tmpdir, "storage.sqlite"))
        s = self._mk()
        s.start()
        self.assertFalse(s.ready)
        self.assertFalse(os.path.exists(os.path.join(self._tmpdir, "storage.sqlite")))

    def test_corrupt_db_rejected(self):
        os.makedirs(self._tmpdir, exist_ok=True)
        with open(os.path.join(self._tmpdir, "storage.sqlite"), "wb") as f:
            f.write(b"not a valid sqlite file at all padding1234")
        s = self._mk()
        s.start()
        self.assertFalse(s.ready)

    # --- Backup: WAL committed rows included ---

    def test_backup_includes_committed_wal_rows(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)

        db_path = os.path.join(self._tmpdir, "storage.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO kv VALUES ('wal_key', 'wal_value')")
        conn.commit()
        # Force checkpoint so WAL data is durable
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        data = s.backup()
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 0)
        self.assertTrue(data[:16].startswith(b"SQLite format 3"))

        # Verify backup contains the WAL-committed row
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp_path = tmp.name
        tmp.write(data)
        tmp.close()
        try:
            c2 = sqlite3.connect(tmp_path)
            rows = c2.execute("SELECT v FROM kv WHERE k='wal_key'").fetchall()
            c2.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "wal_value")
        finally:
            os.unlink(tmp_path)

    # --- Corrupt restore leaves existing DB and process intact ---

    def test_corrupt_restore_preserves_existing_state(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)

        db_path = os.path.join(self._tmpdir, "storage.sqlite")
        original_mtime = os.path.getmtime(db_path)

        # Valid SQLite header but garbage body
        bad = b"SQLite format 3\x00" + b"\x00" * 200
        with self.assertRaises(ValueError):
            s.restore(bad)

        self.assertTrue(s.ready)
        self.assertEqual(os.path.getmtime(db_path), original_mtime)

    def test_non_sqlite_bytes_rejected(self):
        s = self._mk()
        s.start()
        with self.assertRaises(ValueError):
            s.restore(b"this is not sqlite data at all!!!")
        self.assertTrue(s.ready)

    def test_too_small_payload_rejected(self):
        s = self._mk()
        s.start()
        with self.assertRaises(ValueError):
            s.restore(b"tiny")
        self.assertTrue(s.ready)

    def test_non_bytes_rejected(self):
        s = self._mk()
        s.start()
        with self.assertRaises(TypeError):
            s.restore("not bytes")

    # --- Valid restore: stops child, replaces DB, restarts ---

    def test_valid_restore_stops_and_restarts(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)

        backup_data = s.backup()
        self.assertGreater(len(backup_data), 16)

        pid_before = s.child_pid
        self.assertIsNotNone(pid_before)

        s.restore(backup_data)

        self.assertTrue(s.ready)
        self.assertIsNotNone(s.child_pid)
        self.assertTrue(os.path.exists(os.path.join(self._tmpdir, "storage.sqlite")))

    # --- Restart failure: does not ready ---

    def test_restart_failure_stays_unavailable(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)

        backup_data = s.backup()
        # Swap command to something that exits non-zero
        s._command = [sys.executable, "-S", "-c", "import sys; sys.exit(99)"]

        with self.assertRaises(RuntimeError):
            s.restore(backup_data)
        self.assertFalse(s.ready)

    # --- Old DB preserved as .pre_restore ---

    def test_old_db_preserved_after_restore(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)

        db_path = os.path.join(self._tmpdir, "storage.sqlite")
        backup_data = s.backup()

        s.restore(backup_data)
        self.assertTrue(s.ready)

        pre_restore = s.recovery_backup_path
        self.assertTrue(os.path.exists(pre_restore))
        self.assertGreater(os.path.getsize(pre_restore), 0)

    # --- Unrelated files preserved ---

    def test_unrelated_files_preserved(self):
        os.makedirs(self._tmpdir, exist_ok=True)
        unrelated = os.path.join(self._tmpdir, "unrelated.txt")
        with open(unrelated, "w") as f:
            f.write("keep me")

        s = self._mk()
        s.start()
        backup_data = s.backup()
        s.restore(backup_data)

        self.assertTrue(os.path.exists(unrelated))
        with open(unrelated) as f:
            self.assertEqual(f.read(), "keep me")

    # --- Thread serialization ---

    def test_thread_serialization(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)

        errors = []
        results = []

        def do_backup(idx):
            try:
                data = s.backup()
                results.append((idx, len(data)))
            except Exception as e:
                errors.append((idx, e))

        threads = [threading.Thread(target=do_backup, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertEqual(len(results), 4)
        for _, size in results:
            self.assertGreater(size, 0)

    # --- Size bound on restore ---

    def test_oversized_restore_rejected(self):
        s = self._mk()
        s.start()
        huge = b"SQLite format 3\x00" + b"\x00" * (257 * 1024 * 1024)
        with self.assertRaises(ValueError):
            s.restore(huge)
        self.assertTrue(s.ready)

    # --- Backup when DB missing ---

    def test_backup_missing_db_raises(self):
        s = self._mk()
        db = os.path.join(self._tmpdir, "storage.sqlite")
        if os.path.exists(db):
            os.unlink(db)
        with self.assertRaises(FileNotFoundError):
            s.backup()

    # --- Double start / double stop ---

    def test_double_start_keeps_same_child(self):
        s = self._mk()
        s.start()
        pid1 = s.child_pid
        s.start()
        pid2 = s.child_pid
        self.assertIsNotNone(pid2)
        self.assertEqual(pid1, pid2)

    def test_stop_when_no_child(self):
        s = self._mk()
        s.stop()
        self.assertFalse(s.ready)

    # --- Shutdown ---

    def test_shutdown(self):
        s = self._mk()
        s.start()
        self.assertTrue(s.ready)
        s.shutdown()
        self.assertFalse(s.ready)
        self.assertIsNone(s.child_pid)




class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / "company"
        self.data.mkdir(mode=0o700)
        with sqlite3.connect(self.data / "storage.sqlite") as db:
            db.execute("create table evidence(value text)")
            db.execute("insert into evidence values ('original')")
        self.children = []
        self.instances = []

    def make(self, code="import time; time.sleep(10)", admitted=True):
        s = Supervisor(str(self.data), [sys.executable, "-S", "-c", code],
                       "synthetic-storage-secret-for-tests-only",
                       "synthetic-management-secret-for-tests-only", admission=admitted)
        self.instances.append(s)
        return s

    def started(self, s):
        s.start()
        if s._child is not None:
            self.children.append(s._child)

    def tearDown(self):
        for supervisor in self.instances:
            if isinstance(supervisor._child, subprocess.Popen):
                supervisor.stop(timeout=2)
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except Exception:
                    child.kill()
                    child.wait(timeout=2)
        self.tmp.cleanup()



class IndependentReview(ReviewFixture):
    def test_real_child_receives_correct_data_and_storage_key(self):
        observed = self.root / "observed.json"
        code = "import json,os,time; from pathlib import Path; " +             "Path(" + repr(str(observed)) + ").write_text(json.dumps({k:os.environ.get(k) for k in ['DATA_DIR','STORAGE_ENCRYPTION_KEY']})); time.sleep(10)"
        s = self.make(code)
        self.started(s)
        deadline = time.monotonic() + 2
        while not observed.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(observed.exists(), "fixture child did not start")
        env = json.loads(observed.read_text())
        self.assertEqual(env['DATA_DIR'], str(self.data))
        self.assertEqual(env['STORAGE_ENCRYPTION_KEY'], 'synthetic-storage-secret-for-tests-only')

    def test_missing_database_is_not_autocreated_or_ready(self):
        (self.data / "storage.sqlite").unlink()
        s = self.make()
        self.started(s)
        self.assertFalse(s.ready)
        self.assertFalse((self.data / "storage.sqlite").exists())

    def test_later_child_exit_invalidates_readiness(self):
        s = self.make("import time; time.sleep(0.6)")
        self.started(s)
        self.assertTrue(s.ready)
        child = s._child
        child.wait(timeout=2)
        self.assertFalse(s.ready)

    def test_repeated_start_never_leaks_old_child(self):
        s = self.make()
        self.started(s)
        first = s._child
        self.started(s)
        self.assertTrue(s.child_pid == first.pid or first.poll() is not None,
                        "repeated start left an untracked live child")

    def test_dangling_database_symlink_is_rejected(self):
        db = self.data / "storage.sqlite"
        db.unlink()
        outside = self.root / "must-stay-absent.sqlite"
        db.symlink_to(outside)
        s = self.make()
        self.started(s)
        self.assertFalse(s.ready)
        self.assertFalse(outside.exists())



class RecoveryReview(ReviewFixture):
    def incoming(self):
        p = self.root / "incoming.sqlite"
        with sqlite3.connect(p) as db:
            db.execute("create table evidence(value text)")
            db.execute("insert into evidence values ('replacement')")
        return p.read_bytes()

    def test_unrelated_pre_restore_file_is_preserved(self):
        other = self.data / "storage.sqlite.pre_restore"
        other.write_bytes(b"unrelated-owner-file")
        s = self.make()
        self.started(s)
        s.restore(self.incoming())
        if isinstance(s._child, subprocess.Popen): self.children.append(s._child)
        self.assertEqual(other.read_bytes(), b"unrelated-owner-file")

    def test_failed_stop_prevents_replacement_and_keeps_identity(self):
        s = self.make()
        before = (self.data / "storage.sqlite").read_bytes()
        child = mock.Mock()
        child.pid = 999999
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired("owned-fixture", 0.01)
        s._child = child
        s._pgid = child.pid
        try:
            with mock.patch("lib.runtime_supervisor.os.getpgid", return_value=999999), mock.patch("lib.runtime_supervisor.os.killpg"):
                with self.assertRaises(RuntimeError): s.restore(self.incoming())
            self.assertIs(s._child, child)
            self.assertEqual((self.data / "storage.sqlite").read_bytes(), before)
        finally:
            if isinstance(s._child, subprocess.Popen): self.children.append(s._child)

    def test_recovery_snapshot_includes_committed_wal(self):
        writer = sqlite3.connect(self.data / "storage.sqlite")
        writer.execute("pragma journal_mode=WAL")
        writer.execute("pragma wal_autocheckpoint=0")
        writer.execute("insert into evidence values ('committed-wal')")
        writer.commit()
        s = self.make()
        self.started(s)
        try:
            s.restore(self.incoming())
            if isinstance(s._child, subprocess.Popen): self.children.append(s._child)
            path = getattr(s, "recovery_backup_path", self.data / "storage.sqlite.pre_restore")
            with sqlite3.connect(path) as db:
                rows = {r[0] for r in db.execute("select value from evidence")}
            self.assertEqual(rows, {'original', 'committed-wal'})
            with sqlite3.connect(self.data / "storage.sqlite") as db:
                self.assertEqual(list(db.execute("select value from evidence")), [('replacement',)])
        finally:
            writer.close()

    def test_valid_directory_question_and_fragment_chars(self):
        self.data = self.root / "company?question#fragment"
        self.data.mkdir(mode=0o700)
        with sqlite3.connect(self.data / "storage.sqlite") as db:
            db.execute("create table evidence(value text)")
        s = self.make()
        self.started(s)
        self.assertTrue(s.ready)

    def test_symlink_ancestor_is_rejected(self):
        parent = self.root / "parent"
        parent.mkdir()
        nested = parent / "company"
        nested.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(parent, target_is_directory=True)
        self.data = alias / "company"
        with self.assertRaises(ValueError): self.make()

    def test_directory_redirect_after_constructor_is_held(self):
        s = self.make()
        original = self.data
        retained = self.root / "retained-company"
        original.rename(retained)
        original.symlink_to(retained, target_is_directory=True)
        self.started(s)
        self.assertFalse(s.ready)
        self.assertIsNone(s.child_pid)

    def test_sidecar_symlink_cannot_modify_external_file(self):
        target = self.root / "outside-sentinel"
        target.write_bytes(b"preserve")
        (self.data / "storage.sqlite-wal").symlink_to(target)
        s = self.make()
        before = (self.data / "storage.sqlite").read_bytes()
        with self.assertRaises(ValueError): s.restore(self.incoming())
        self.assertEqual(target.read_bytes(), b"preserve")
        self.assertEqual((self.data / "storage.sqlite").read_bytes(), before)

    def test_backup_deadline_aborts_without_source_changes(self):
        s = self.make()
        before = (self.data / "storage.sqlite").read_bytes()
        with mock.patch("lib.runtime_supervisor.time.monotonic", side_effect=[0, 20]):
            with self.assertRaisesRegex(RuntimeError, "deadline"): s.backup()
        self.assertEqual((self.data / "storage.sqlite").read_bytes(), before)

    def test_failed_replace_retains_consistent_recovery_copy(self):
        s = self.make()
        self.started(s)
        before = (self.data / "storage.sqlite").read_bytes()
        with mock.patch("lib.runtime_supervisor.os.replace", side_effect=OSError("fixture replace failure")):
            with self.assertRaises(OSError): s.restore(self.incoming())
        self.assertFalse(s.ready)
        self.assertEqual((self.data / "storage.sqlite").read_bytes(), before)
        with sqlite3.connect(s.recovery_backup_path) as db:
            self.assertEqual(list(db.execute("select value from evidence")), [('original',)])

    def test_dead_launcher_does_not_skip_owned_group_shutdown(self):
        s = self.make()
        launcher = mock.Mock()
        launcher.pid = 999999
        launcher.poll.return_value = 0
        s._child = launcher
        s._pgid = launcher.pid
        with mock.patch("lib.runtime_supervisor.os.killpg", side_effect=[None, ProcessLookupError()]) as signal_group:
            s.stop(timeout=0.01)
        self.assertTrue(signal_group.called, "dead launcher must not bypass descendant shutdown")

    def test_actual_orphan_descendant_is_stopped(self):
        import sys, time, signal
        pid_file = self.root / "descendant.pid"
        child_code = "import sqlite3,time; c=sqlite3.connect(" + repr(str(self.data / "storage.sqlite")) + "); time.sleep(30)"
        leader_code = ("import subprocess,sys; from pathlib import Path; "
                       "p=subprocess.Popen([sys.executable,'-S','-c'," + repr(child_code) + "],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                       "Path(" + repr(str(pid_file)) + ").write_text(str(p.pid))")
        s = self.make(leader_code)
        self.started(s)
        launcher = s._child
        child_pid = None
        try:
            launcher.wait(timeout=5)
            child_pid = int(pid_file.read_text())
            os.kill(child_pid, 0)
            s.stop(timeout=1)
            self.assertIsNone(s.child_pid)
            with self.assertRaises(ProcessLookupError): os.kill(child_pid, 0)
        finally:
            try: os.killpg(launcher.pid, signal.SIGKILL)
            except ProcessLookupError: pass

    def test_live_group_after_leader_exit_blocks_restore(self):
        s = self.make()
        old_bytes = (self.data / "storage.sqlite").read_bytes()
        leader = mock.Mock()
        leader.pid = 999999
        leader.poll.return_value = 0
        s._child = leader
        s._pgid = leader.pid
        with mock.patch("lib.runtime_supervisor.os.killpg"), mock.patch.object(s, "_await_group_exit", return_value=False):
            with self.assertRaises(RuntimeError): s.restore(self.incoming())
        self.assertIs(s._child, leader)
        self.assertEqual((self.data / "storage.sqlite").read_bytes(), old_bytes)

    def test_runtime_port_rejects_invalid_or_ambiguous_values(self):
        from lib.runtime_supervisor import Supervisor
        for port in [True, "8081", 0, 65536, None]:
            with self.subTest(port=port), self.assertRaises(ValueError):
                Supervisor(str(self.data), ["unused"], "fixture-key", "fixture-management", runtime_port=port)

    def test_permission_denied_group_probe_is_not_absence(self):
        s = self.make()
        s._pgid = 999999
        with mock.patch("lib.runtime_supervisor.os.killpg", side_effect=PermissionError()):
            self.assertTrue(s._group_exists())

    def test_transient_permission_probe_requires_later_verified_absence(self):
        s = self.make()
        leader = mock.Mock()
        leader.pid = 999999
        leader.poll.return_value = 0
        s._child = leader
        s._pgid = leader.pid
        with mock.patch("lib.runtime_supervisor.os.killpg", side_effect=[None, PermissionError(), ProcessLookupError()]):
            s.stop(timeout=.1)
        self.assertIsNone(s.child_pid)

    def test_persistent_signal_permission_denial_holds_database(self):
        s = self.make()
        leader = mock.Mock()
        leader.pid = 999999
        leader.poll.return_value = 0
        s._child = leader
        s._pgid = leader.pid
        before = (self.data / "storage.sqlite").read_bytes()
        with mock.patch("lib.runtime_supervisor.os.killpg", side_effect=PermissionError()), mock.patch.object(s, "_await_group_exit", return_value=False):
            with self.assertRaises(RuntimeError): s.restore(self.incoming())
        self.assertIs(s._child, leader)
        self.assertEqual((self.data / "storage.sqlite").read_bytes(), before)


class TestBackupQuota(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        self.db = self.root / "storage.sqlite"
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE fixture(value BLOB)")
            connection.execute("INSERT INTO fixture VALUES ('original')")
        self.supervisor = Supervisor(str(self.root), [sys.executable, "-c", "pass"], TEST_KEY, TEST_SECRET)

    def tearDown(self):
        self.directory.cleanup()

    def enlarge(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("INSERT INTO fixture VALUES (zeroblob(?))", (65 * 1024 * 1024,))

    def test_oversized_backup_denied_without_artifact(self):
        self.enlarge()
        before = set(self.root.iterdir())
        with self.assertRaises(RuntimeError):
            self.supervisor.backup()
        self.assertEqual(before, set(self.root.iterdir()))

    def test_restore_preserves_oversized_current_state(self):
        incoming = self.supervisor.backup()
        self.enlarge()
        with mock.patch.object(self.supervisor, "_stop_impl") as stop:
            with self.assertRaises(RuntimeError):
                self.supervisor.restore(incoming)
            stop.assert_not_called()
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM fixture").fetchone()[0], 2)

    def test_deadline_after_integrity_check_denied(self):
        now = [100.0]
        check = self.supervisor._sqlite_quick_check
        def slow_check(path):
            result = check(path)
            now[0] = 111.0
            return result
        with mock.patch("lib.runtime_supervisor.time.monotonic", side_effect=lambda: now[0]), mock.patch.object(self.supervisor, "_sqlite_quick_check", side_effect=slow_check):
            with self.assertRaises(RuntimeError):
                self.supervisor.backup()

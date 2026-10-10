"""Supervisor: strict lifecycle manager for a single child process with SQLite storage.

Production context: OmniRoute 3.8.50 / Node24. DATA_DIR is an exact owned directory.
storage.sqlite is real SQLite. STORAGE_ENCRYPTION_KEY is required and independently durable.
Actual runtime command is explicit non-shell argv supplied by caller.
"""

import os
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
import stat
from urllib.parse import quote

_MAX_RESTORE_BYTES = 256 * 1024 * 1024
_SQLITE_HEADER = b"SQLite format 3\x00"


class Supervisor:
    """Manages a child process with SQLite-backed state.

    State is *unavailable* until ALL of:
      - child process is alive
      - storage.sqlite passes read-only quick_check
      - explicit admission granted (admission flag)

    Backup returns raw SQLite bytes (including committed WAL).
    Restore validates in temp, stops child, replaces DB, restarts.
    All lifecycle/backup/restore serialized via thread lock.
    """

    def __init__(self, data_dir, command, storage_key, management_secret, admission=False, runtime_port=8081):
        if not storage_key or not isinstance(storage_key, str):
            raise ValueError("storage_key required")
        if not management_secret or not isinstance(management_secret, str):
            raise ValueError("management_secret required")
        if not data_dir or not isinstance(data_dir, str):
            raise ValueError("data_dir required")
        if os.path.islink(data_dir):
            raise ValueError("data_dir must not be a symlink")
        if not command or not isinstance(command, (list, tuple)) or len(command) == 0:
            raise ValueError("command required as non-empty list")

        if type(runtime_port) is not int or not 1 <= runtime_port <= 65535:
            raise ValueError("runtime_port must be an integer from 1 to 65535")
        self._runtime_port = runtime_port

        resolved = os.path.realpath(data_dir)
        if resolved != os.path.abspath(data_dir):
            raise ValueError("data_dir must be canonical without symlink ancestors")
        self._data_dir = resolved
        self._command = list(command)
        self._storage_key = storage_key
        self._management_secret = management_secret
        self._admission = bool(admission)
        self._db_path = os.path.join(resolved, "storage.sqlite")

        self._child = None
        self._pgid = None
        self._ready = False
        self._lock = threading.Lock()
        self.recovery_backup_path = None

    # --- Properties ---

    @property
    def ready(self):
        with self._lock:
            try:
                self._preflight()
                if (self._child is None or self._child.poll() is not None
                        or not self._admission or not self._sqlite_quick_check(self._db_path)):
                    self._ready = False
            except (OSError, ValueError):
                self._ready = False
            return self._ready

    @property
    def child_pid(self):
        return self._child.pid if self._child else None

    # --- Preflight ---

    def _preflight(self):
        if os.path.realpath(self._data_dir) != self._data_dir:
            raise ValueError("data directory moved behind a symlink")
        if not os.path.isdir(self._data_dir):
            raise FileNotFoundError(f"data_dir not found: {self._data_dir}")
        if not os.access(self._data_dir, os.W_OK):
            raise PermissionError(f"data_dir not writable: {self._data_dir}")
        if os.stat(self._data_dir).st_uid != os.geteuid():
            raise ValueError("data directory is not owned by this operator")
        for path in (self._db_path, self._db_path + "-wal", self._db_path + "-shm"):
            if os.path.lexists(path):
                entry = os.lstat(path)
                if not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.geteuid():
                    raise ValueError("database or sidecar is not an owned regular file")

    def _validate_sqlite_header(self, data):
        if not isinstance(data, (bytes, bytearray)):
            return False
        if len(data) < 16:
            return False
        return bytes(data[:16]) == _SQLITE_HEADER

    def _sqlite_quick_check(self, path):
        try:
            with open(path, "rb") as database:
                if database.read(16) != _SQLITE_HEADER:
                    return False
            conn = sqlite3.connect(f"file:{quote(path, safe='/')}?mode=ro", uri=True)
            try:
                result = conn.execute("PRAGMA quick_check").fetchone()
                return result is not None and result[0] == "ok"
            finally:
                conn.close()
        except Exception:
            return False

    # --- Internal lifecycle (no lock) ---

    def _start_impl(self):
        """Start child and check readiness. Caller must hold lock."""
        self._ready = False
        try:
            self._preflight()
            if not os.path.exists(self._db_path):
                return
            if self._child is not None and self._child.poll() is None:
                self._ready = self._admission and self._sqlite_quick_check(self._db_path)
                return

            if self._child is not None:
                self._stop_impl()

            env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": self._data_dir,
                "DATA_DIR": self._data_dir,
                "STORAGE_ENCRYPTION_KEY": self._storage_key,
                "PORT": str(self._runtime_port),
                "HOSTNAME": "127.0.0.1",
                "NEXT_TELEMETRY_DISABLED": "1",
            }
            self._child = subprocess.Popen(
                self._command,
                shell=False,
                start_new_session=True,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            self._pgid = self._child.pid  # start_new_session makes this the owned group id
            time.sleep(0.15)
            if self._child.poll() is not None:
                self._ready = False
                return

            if self._sqlite_quick_check(self._db_path) and self._admission:
                self._ready = True
            else:
                self._ready = False
        except Exception:
            self._ready = False

    def _group_exists(self):
        """An owned group remains held even if only an unreaped descendant survives."""
        try:
            os.killpg(self._pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # A denied existence probe is inconclusive, never proof of absence.
            return True

    def _await_group_exit(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            self._child.poll()  # reap the directly owned leader
            if not self._group_exists():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def _stop_impl(self, timeout=5.0):
        """Stop the entire owned group before allowing database replacement."""
        self._ready = False
        if self._child is None:
            return
        if self._pgid is None:
            raise RuntimeError("managed process group identity unavailable; database remains held")
        try:
            os.killpg(self._pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        if not self._await_group_exit(timeout):
            try:
                os.killpg(self._pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            if not self._await_group_exit(2.0):
                raise RuntimeError("managed process group did not stop; database remains held")
        try:
            self._child.wait(timeout=2)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("managed child did not stop; database remains held") from exc
        if self._child.poll() is None:
            raise RuntimeError("managed child remains alive")
        self._child = None
        self._pgid = None

    # --- Public lifecycle (acquires lock) ---

    def start(self):
        with self._lock:
            self._start_impl()

    def stop(self, timeout=5.0):
        with self._lock:
            self._stop_impl(timeout)

    # --- Backup ---

    def backup(self):
        with self._lock:
            return self._backup_impl()

    def _backup_impl(self):
        self._preflight()
        if not os.path.exists(self._db_path):
            raise FileNotFoundError("no storage.sqlite")
        cap = 64 * 1024 * 1024
        deadline = time.monotonic() + 10.0
        tmp = tempfile.NamedTemporaryFile(dir=self._data_dir, suffix=".sqlite", delete=False)
        tmp_path = tmp.name
        tmp.close()
        try:
            src = sqlite3.connect(f"file:{quote(self._db_path, safe='/')}?mode=ro", uri=True)
            try:
                cur = src.cursor()
                page_size = cur.execute("PRAGMA page_size").fetchone()[0]
                page_count = cur.execute("PRAGMA page_count").fetchone()[0]
                cur.close()
                if page_count * page_size > cap:
                    raise RuntimeError("backup size exceeds quota")
                def progress(status, remaining, total):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("SQLite backup deadline exceeded")
                    if total * page_size > cap:
                        raise RuntimeError("backup size exceeds quota")
                dst = sqlite3.connect(tmp_path)
                try:
                    src.backup(dst, pages=16, progress=progress, sleep=0.01)
                finally:
                    dst.close()
            finally:
                src.close()
            st_size = os.path.getsize(tmp_path)
            if st_size < 1 or st_size > cap:
                raise RuntimeError("invalid backup file size")
            if not self._sqlite_quick_check(tmp_path):
                raise RuntimeError("backup validation failed")
            with open(tmp_path, "rb") as f:
                data = f.read(cap + 1)
            if len(data) != st_size or len(data) > cap:
                raise RuntimeError("backup data size mismatch or quota exceeded")
            if time.monotonic() >= deadline:
                raise RuntimeError("SQLite backup deadline exceeded")
            return data
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # --- Restore ---

    def restore(self, incoming_bytes):
        with self._lock:
            self._preflight()
            if not isinstance(incoming_bytes, (bytes, bytearray)):
                raise TypeError("incoming must be bytes")
            if len(incoming_bytes) > _MAX_RESTORE_BYTES:
                raise ValueError("incoming exceeds size limit")
            if not self._validate_sqlite_header(incoming_bytes):
                raise ValueError("invalid SQLite header")

            tmp = tempfile.NamedTemporaryFile(
                dir=self._data_dir, suffix=".sqlite", delete=False
            )
            tmp_path = tmp.name
            tmp.close()
            try:
                with open(tmp_path, "wb") as f:
                    f.write(incoming_bytes)
                    f.flush()
                    os.fsync(f.fileno())
                if not self._sqlite_quick_check(tmp_path):
                    raise ValueError("incoming failed quick_check")
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            self._ready = False
            try:
                if os.path.exists(self._db_path):
                    original = self._backup_impl()
                    with tempfile.NamedTemporaryFile(dir=self._data_dir,
                            prefix=".sg-recovery-", suffix=".sqlite", delete=False) as snapshot:
                        snapshot.write(original)
                        snapshot.flush()
                        os.fsync(snapshot.fileno())
                        self.recovery_backup_path = snapshot.name
                    parent_fd = os.open(self._data_dir, os.O_RDONLY)
                    try:
                        os.fsync(parent_fd)
                    finally:
                        os.close(parent_fd)
                self._stop_impl(timeout=5.0)
                self._preflight()
                if os.path.exists(self._db_path):
                    conn = sqlite3.connect(f"file:{quote(self._db_path, safe='/')}?mode=rw", uri=True)
                    try:
                        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                        if checkpoint[0] != 0:
                            raise RuntimeError("SQLite WAL remains busy; restore held")
                    finally:
                        conn.close()
                self._preflight()
                for suffix in ("-wal", "-shm"):
                    sidecar = self._db_path + suffix
                    if os.path.lexists(sidecar):
                        os.unlink(sidecar)
                os.replace(tmp_path, self._db_path)
                fd = os.open(self._db_path, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                parent_fd = os.open(self._data_dir, os.O_RDONLY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except Exception:
                self._ready = False
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
            self._start_impl()
            if (self._child is None or self._child.poll() is not None
                    or not self._sqlite_quick_check(self._db_path)):
                self._ready = False
                raise RuntimeError("restored child failed; recovery snapshot retained")

    def shutdown(self):
        with self._lock:
            self._stop_impl(timeout=5.0)

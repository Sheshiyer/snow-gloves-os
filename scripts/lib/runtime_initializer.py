"""Runtime Initializer Library

Provides InitializingSupervisor for fresh runtime initialization.
"""

import http.client
import math
import os
import sqlite3
import subprocess
import time
import urllib.parse
from scripts.lib.runtime_supervisor import Supervisor


class InitializingSupervisor(Supervisor):
    """Supervisor supporting explicit fresh runtime initialization."""

    def __init__(
        self,
        data_dir,
        command,
        storage_key,
        management_secret,
        admission=False,
        runtime_port=8081,
    ):
        super().__init__(
            data_dir,
            command,
            storage_key,
            management_secret,
            admission=admission,
            runtime_port=runtime_port,
        )
        self._init_attempted = False

    def _verify_empty_canonical_dir(self):
        current_uid = os.getuid()
        raw_path = str(self._data_dir)
        real_path = os.path.realpath(raw_path)
        if raw_path != real_path:
            raise RuntimeError("Invalid directory path")

        # Verify no symlink ancestors
        parts = real_path.split(os.sep)
        accum = "/"
        for part in parts:
            if not part:
                continue
            accum = os.path.join(accum, part)
            if os.path.islink(accum):
                raise RuntimeError("Symlink ancestor detected")

        st = os.stat(real_path)
        if not os.path.isdir(real_path):
            raise RuntimeError("Not a directory")
        if st.st_uid != current_uid:
            raise RuntimeError("Directory ownership mismatch")
        if (st.st_mode & 0o077) != 0:
            raise RuntimeError("Insecure directory permissions")

        entries = os.listdir(real_path)
        if len(entries) > 0:
            raise RuntimeError("Directory is not empty")

        return st.st_dev, st.st_ino

    def _check_schema_tables(self):
        db_file = str(self._db_path)
        if not os.path.isfile(db_file):
            return False
        quoted_path = urllib.parse.quote(os.path.abspath(db_file))
        uri = f"file:{quoted_path}?mode=ro"
        conn = None
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            row = cursor.fetchone()
            if row is not None and row[0] > 0:
                return True
            return False
        except Exception:
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _check_http_health(self):
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port=int(self._runtime_port), timeout=1.0)
            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            if resp.status != 200:
                return False
            body = resp.read(16)
            if body == b"ok\n":
                return True
            return False
        except Exception:
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def initialize_fresh(self, *, authorized=False, timeout=60.0):
        try:
            return self._initialize_fresh_impl(authorized=authorized, timeout=timeout)
        except Exception:
            raise RuntimeError("Runtime initialization failed") from None

    def _initialize_fresh_impl(self, *, authorized=False, timeout=60.0):
        if authorized is not True:
            raise RuntimeError("Unauthorized initialization")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise RuntimeError("Invalid timeout value")
        if not math.isfinite(timeout) or timeout <= 0.0 or timeout > 120.0:
            raise RuntimeError("Invalid timeout range")

        with self._lock:
            if self._init_attempted:
                raise RuntimeError("Initialization already attempted on this instance")
            if self._child is not None or self._pgid is not None:
                raise RuntimeError("Existing process or process group active")

            root_dev, root_ino = self._verify_empty_canonical_dir()
            self._init_attempted = True

            child_env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": str(self._data_dir),
                "DATA_DIR": str(self._data_dir),
                "STORAGE_ENCRYPTION_KEY": str(self._storage_key),
                "PORT": str(self._runtime_port),
                "HOSTNAME": "127.0.0.1",
                "NEXT_TELEMETRY_DISABLED": "1",
            }

            spawned = False
            try:
                child = subprocess.Popen(
                    self._command,
                    env=child_env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self._child = child
                self._pgid = child.pid
                spawned = True
            except Exception:
                raise RuntimeError("Runtime initialization failed")

            deadline = time.monotonic() + float(timeout)
            success = False
            try:
                while time.monotonic() < deadline:
                    # Verify child is alive
                    if self._child.poll() is not None:
                        raise RuntimeError("Process exited prematurely")

                    # Verify directory identity
                    try:
                        st = os.stat(str(self._data_dir))
                        if st.st_dev != root_dev or st.st_ino != root_ino:
                            raise RuntimeError("Directory drift detected")
                    except Exception:
                        raise RuntimeError("Directory access error")

                    # Preflight check
                    preflight_ok = False
                    try:
                        self._preflight()
                        preflight_ok = True
                    except Exception:
                        preflight_ok = False

                    if preflight_ok:
                        sqlite_ok = False
                        try:
                            sqlite_ok = self._sqlite_quick_check(self._db_path)
                        except Exception:
                            sqlite_ok = False

                        if sqlite_ok and self._check_schema_tables() and self._check_http_health():
                            self._preflight()
                            final_root = os.lstat(self._data_dir)
                            if (final_root.st_dev != root_dev or final_root.st_ino != root_ino or
                                    final_root.st_uid != os.geteuid() or final_root.st_mode & 0o077):
                                raise RuntimeError("Runtime initialization failed")
                            if time.monotonic() >= deadline:
                                raise RuntimeError("Runtime initialization failed")
                            success = True
                            break

                    sleep_duration = min(0.1, max(0.01, deadline - time.monotonic()))
                    if sleep_duration > 0:
                        time.sleep(sleep_duration)

                if not success:
                    raise RuntimeError("Runtime initialization failed")

                if self._admission:
                    self._ready = True
                else:
                    self._ready = False

                return True
            except (KeyboardInterrupt, SystemExit):
                self._ready = False
                if spawned:
                    try:
                        self._stop_impl()
                    except Exception:
                        pass
                raise
            except Exception:
                self._ready = False
                if spawned:
                    try:
                        self._stop_impl()
                    except Exception:
                        pass
                raise RuntimeError("Runtime initialization failed")

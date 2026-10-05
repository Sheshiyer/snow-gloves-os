import fcntl
import json
import os
import secrets
import stat
import threading
from lib.runtime_job_journal import _publish_new
from lib.runtime_operation_identity import validate_restore, checkpoint_digest
import sys
from contextlib import contextmanager

_SCHEMA = "sg.restore-intent.v1"
_STATES = {"prepared", "mutation-intent", "completed-local"}
_MAX_RECORD_SIZE = 2048


def _hold():
    raise RuntimeError("Restore intent held") from None


def _verify_root_path_strict(root_path: str) -> str:
    if type(root_path) is not str or not root_path.startswith("/"):
        _hold()
    norm = os.path.normpath(root_path)
    if norm != root_path or root_path in ("/", "/.", "/.."):
        _hold()
    cur = "/"
    for part in [p for p in root_path.split("/") if p]:
        cur = cur + part if cur == "/" else f"{cur}/{part}"
        try:
            st = os.lstat(cur)
        except (OSError, ValueError):
            _hold()
        if stat.S_ISLNK(st.st_mode):
            _hold()
    return root_path


class RestoreIntentStore:
    def __init__(self, root_path, context):
        try:
            if sys.platform != "linux" or type(root_path) is not str:
                _hold()
            self._root_path = _verify_root_path_strict(root_path)
            if type(context) is not dict:
                _hold()
            self._context = dict(context)
            checkpoint_digest(self._context, "0"*32)
            self._tokens = {}
            self._lock = threading.Lock()
            rfd = os.open(self._root_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                st = os.fstat(rfd)
                if not stat.S_ISDIR(st.st_mode) or (st.st_mode & 0o777) != 0o700 or st.st_uid != os.geteuid():
                    _hold()
            finally:
                os.close(rfd)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()

    @contextmanager
    def _locked(self):
        if not self._lock.acquire(blocking=False):
            _hold()
        try:
            yield
        finally:
            self._lock.release()

    def _validate(self, payload):
        try:
            return validate_restore(self._context, payload)
        except Exception:
            _hold()

    def _open_root(self):
        _verify_root_path_strict(self._root_path)
        rfd = os.open(self._root_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            st = os.fstat(rfd)
            if not stat.S_ISDIR(st.st_mode) or (st.st_mode & 0o777) != 0o700 or st.st_uid != os.geteuid():
                _hold()
            try:
                p_st = os.stat(self._root_path)
                if (p_st.st_dev, p_st.st_ino) != (st.st_dev, st.st_ino):
                    _hold()
            except OSError:
                _hold()
            try:
                fcntl.flock(rfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, IOError):
                _hold()
            return rfd, st.st_dev, st.st_ino
        except Exception:
            os.close(rfd)
            raise

    def _verify_root(self, rfd, r_dev, r_ino):
        try:
            _verify_root_path_strict(self._root_path)
            descriptor = os.fstat(rfd)
            named = os.lstat(self._root_path)
            for value in (descriptor, named):
                if (not stat.S_ISDIR(value.st_mode)
                    or value.st_uid != os.geteuid()
                    or stat.S_IMODE(value.st_mode) != 0o700
                    or (value.st_dev, value.st_ino) != (r_dev, r_ino)):
                    _hold()
        except OSError:
            _hold()

    def _close_root(self, rfd):
        try:
            try:
                fcntl.flock(rfd, fcntl.LOCK_UN)
            except OSError:
                pass
        finally:
            os.close(rfd)

    def _encode_record(self, payload, state):
        if state not in _STATES:
            _hold()
        record = {"payload": payload, "schema": _SCHEMA, "state": state}
        raw = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(raw) > _MAX_RECORD_SIZE:
            _hold()
        return raw, record

    def _parse_and_validate_raw(self, raw_bytes, expected_payload):
        if len(raw_bytes) > _MAX_RECORD_SIZE:
            _hold()
        try:
            text = raw_bytes.decode("utf-8")
            pairs = []

            def _hook(p):
                keys = [k for k, _ in p]
                if len(keys) != len(set(keys)):
                    _hold()
                d = dict(p)
                pairs.append(d)
                return d

            data = json.loads(text, object_pairs_hook=_hook)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if type(data) is not dict or set(data.keys()) != {"schema", "payload", "state"}:
            _hold()
        if data.get("schema") != _SCHEMA or data.get("state") not in _STATES:
            _hold()
        try:
            v_payload = validate_restore(self._context, data["payload"])
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            _hold()
        if expected_payload is not None and v_payload != expected_payload:
            _hold()
        canon_raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if canon_raw != raw_bytes:
            _hold()
        return {"schema": _SCHEMA, "payload": v_payload, "state": data["state"]}

    def _read_existing(self, rfd, filename, r_dev, r_ino, expected_payload):
        self._verify_root(rfd, r_dev, r_ino)
        try:
            ffd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=rfd)
        except FileNotFoundError:
            return None, None, None
        except OSError:
            _hold()
        try:
            st1 = os.fstat(ffd)
            if not stat.S_ISREG(st1.st_mode) or (st1.st_mode & 0o777) != 0o600:
                _hold()
            if st1.st_uid != os.geteuid() or st1.st_nlink != 1 or st1.st_size > _MAX_RECORD_SIZE:
                _hold()
            if st1.st_dev != r_dev:
                _hold()
            raw = os.read(ffd, _MAX_RECORD_SIZE + 1)
            if len(raw) > _MAX_RECORD_SIZE or len(raw) != st1.st_size:
                _hold()
            st2 = os.fstat(ffd)
            if (
                st1.st_ino != st2.st_ino
                or st1.st_dev != st2.st_dev
                or st1.st_size != st2.st_size
                or st1.st_mtime_ns != st2.st_mtime_ns
                or st1.st_ctime_ns != st2.st_ctime_ns
            ):
                _hold()
            meta = (st2.st_ino, st2.st_dev, st2.st_size, st2.st_mtime_ns, st2.st_ctime_ns)
            rec = self._parse_and_validate_raw(raw, expected_payload)
            self._verify_root(rfd, r_dev, r_ino)
            try:
                named = os.stat(filename, dir_fd=rfd, follow_symlinks=False)
            except OSError:
                _hold()
            final = os.fstat(ffd)
            def signature(value):
                return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                        value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if signature(named) != signature(st2) or signature(final) != signature(st2):
                _hold()
            return rec, raw, meta
        finally:
            os.close(ffd)

    def _verify_temp(self, rfd, temp_name, exp_ino, exp_raw, r_dev, r_ino):
        record, raw, meta = self._read_existing(rfd, temp_name, r_dev, r_ino, None)
        if record is None or raw != exp_raw or meta[0] != exp_ino:
            _hold()

    def _cleanup_temp(self, rfd, temp_name, exp_ino, exp_raw):
        try:
            tfd = os.open(temp_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=rfd)
            try:
                st = os.fstat(tfd)
                if (stat.S_ISREG(st.st_mode) and st.st_ino == exp_ino
                    and st.st_uid == os.geteuid() and st.st_nlink == 1
                    and stat.S_IMODE(st.st_mode) == 0o600
                    and st.st_dev == os.fstat(rfd).st_dev
                    and st.st_size == len(exp_raw)):
                    content = os.read(tfd, len(exp_raw) + 1)
                    final = os.fstat(tfd)
                    named = os.stat(temp_name, dir_fd=rfd, follow_symlinks=False)
                    def signature(value):
                        return (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                                value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
                    if content == exp_raw and signature(st) == signature(final) == signature(named):
                        os.unlink(temp_name, dir_fd=rfd)
            finally:
                os.close(tfd)
        except OSError:
            pass

    def _write_temp_file(self, rfd, raw_bytes, r_dev):
        temp_name = f".tmp-restore-{secrets.token_hex(16)}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            tfd = os.open(temp_name, flags, 0o600, dir_fd=rfd)
        except OSError:
            _hold()
        original_inode = os.fstat(tfd).st_ino
        try:
            os.write(tfd, raw_bytes)
            os.fsync(tfd)
            t_st = os.fstat(tfd)
            if not stat.S_ISREG(t_st.st_mode) or (t_st.st_mode & 0o777) != 0o600:
                _hold()
            if t_st.st_uid != os.geteuid() or t_st.st_nlink != 1 or t_st.st_size != len(raw_bytes):
                _hold()
            if t_st.st_dev != r_dev:
                _hold()
            return temp_name, t_st.st_ino
        except Exception:
            self._cleanup_temp(rfd, temp_name, original_inode, raw_bytes)
            _hold()
        finally:
            os.close(tfd)

    def prepare(self, payload):
        with self._locked():
            v_payload = self._validate(payload)
            job_id = v_payload["restore_job_id"]
            filename = f"sg-restore-{job_id}.json"
            rfd, r_dev, r_ino = self._open_root()
            try:
                rec, _, _ = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                if rec is not None:
                    if rec["state"] in ("prepared", "completed-local") and rec["payload"] == v_payload:
                        return rec
                    _hold()
                raw_bytes, record = self._encode_record(v_payload, "prepared")
                temp_name, t_ino = self._write_temp_file(rfd, raw_bytes, r_dev)
                published = False
                try:
                    self._verify_root(rfd, r_dev, r_ino)
                    self._verify_temp(rfd, temp_name, t_ino, raw_bytes, r_dev, r_ino)
                    _publish_new(rfd, temp_name, filename)
                    published = True
                finally:
                    if not published:
                        self._cleanup_temp(rfd, temp_name, t_ino, raw_bytes)
                try:
                    os.fsync(rfd)
                except OSError:
                    _hold()
                r_rec, r_raw, r_meta = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                if r_rec is None or r_raw != raw_bytes or r_rec != record or r_meta[0] != t_ino:
                    _hold()
                return record
            finally:
                self._close_root(rfd)

    def begin_mutation(self, payload):
        with self._locked():
            v_payload = self._validate(payload)
            job_id = v_payload["restore_job_id"]
            filename = f"sg-restore-{job_id}.json"
            rfd, r_dev, r_ino = self._open_root()
            try:
                rec, old_raw, old_meta = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                if rec is None or rec["state"] != "prepared" or rec["payload"] != v_payload:
                    _hold()
                raw_bytes, _ = self._encode_record(v_payload, "mutation-intent")
                temp_name, t_ino = self._write_temp_file(rfd, raw_bytes, r_dev)
                renamed = False
                try:
                    cur_rec, cur_raw, cur_meta = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                    if cur_rec != rec or cur_raw != old_raw or cur_meta != old_meta:
                        _hold()
                    self._verify_root(rfd, r_dev, r_ino)
                    self._verify_temp(rfd, temp_name, t_ino, raw_bytes, r_dev, r_ino)
                    os.rename(temp_name, filename, src_dir_fd=rfd, dst_dir_fd=rfd)
                    renamed = True
                finally:
                    if not renamed:
                        self._cleanup_temp(rfd, temp_name, t_ino, raw_bytes)
                try:
                    os.fsync(rfd)
                except OSError:
                    _hold()
                r_rec, r_raw, r_meta = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                if r_rec is None or r_raw != raw_bytes or r_rec["state"] != "mutation-intent" or r_meta[0] != t_ino:
                    _hold()
                token = object()
                self._tokens[job_id] = token
                return token
            finally:
                self._close_root(rfd)

    def complete(self, payload, token, *, health_verified=False):
        if health_verified is not True:
            _hold()
        with self._locked():
            v_payload = self._validate(payload)
            job_id = v_payload["restore_job_id"]
            active_token = self._tokens.get(job_id)
            if active_token is None or active_token is not token:
                _hold()
            filename = f"sg-restore-{job_id}.json"
            rfd, r_dev, r_ino = self._open_root()
            try:
                rec, old_raw, old_meta = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                if rec is None or rec["state"] != "mutation-intent" or rec["payload"] != v_payload:
                    _hold()
                raw_bytes, record = self._encode_record(v_payload, "completed-local")
                temp_name, t_ino = self._write_temp_file(rfd, raw_bytes, r_dev)
                renamed = False
                try:
                    cur_rec, cur_raw, cur_meta = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                    if cur_rec != rec or cur_raw != old_raw or cur_meta != old_meta:
                        _hold()
                    self._verify_root(rfd, r_dev, r_ino)
                    self._verify_temp(rfd, temp_name, t_ino, raw_bytes, r_dev, r_ino)
                    os.rename(temp_name, filename, src_dir_fd=rfd, dst_dir_fd=rfd)
                    renamed = True
                finally:
                    if not renamed:
                        self._cleanup_temp(rfd, temp_name, t_ino, raw_bytes)
                try:
                    os.fsync(rfd)
                except OSError:
                    _hold()
                r_rec, r_raw, r_meta = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                if r_rec is None or r_raw != raw_bytes or r_rec != record or r_meta[0] != t_ino:
                    _hold()
                self._tokens.pop(job_id, None)
                return record
            finally:
                self._close_root(rfd)

    def reconcile(self, payload):
        with self._locked():
            v_payload = self._validate(payload)
            job_id = v_payload["restore_job_id"]
            filename = f"sg-restore-{job_id}.json"
            rfd, r_dev, r_ino = self._open_root()
            try:
                rec, _, _ = self._read_existing(rfd, filename, r_dev, r_ino, v_payload)
                if rec is None or rec["state"] == "mutation-intent":
                    _hold()
                if rec["payload"] != v_payload:
                    _hold()
                return rec
            finally:
                self._close_root(rfd)

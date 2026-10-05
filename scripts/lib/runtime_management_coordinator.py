from lib.runtime_bounded_process import run_bounded
import os, sys, stat, json, base64, secrets, hashlib, subprocess, threading, time
from lib.runtime_operation_identity import checkpoint_digest, validate_checkpoint, validate_restore
from lib.runtime_snapshot import write_bounded_snapshot
from lib.runtime_job_journal import LocalJobJournal
from lib.runtime_restore_intent import RestoreIntentStore

SQLITE_HEADER = b"SQLite format 3\x00"
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
MAX_ENCRYPTED_BYTES = MAX_SNAPSHOT_BYTES + 4136

class RuntimeManagementCoordinator:
    def __init__(self, supervisor, context, backup_key_base64, node_executable, backup_cli_path):
        self._lock = threading.Lock()
        try:
            if not isinstance(context, dict):
                raise ValueError("context must be dict")
            for k in ("instanceId", "runtimeVersion", "imageDigest", "keyId"):
                if k not in context or not isinstance(context[k], str):
                    raise ValueError(f"missing {k}")
            if context["runtimeVersion"] != "3.8.50":
                raise ValueError("invalid runtimeVersion")
            if len(context["imageDigest"]) != 64 or any(c not in "0123456789abcdefABCDEF" for c in context["imageDigest"]):
                raise ValueError("invalid imageDigest")
            if not context["keyId"] or any(not (c.isalnum() or c == '-') for c in context["keyId"]) or context["keyId"].lower() != context["keyId"]:
                raise ValueError("invalid keyId")
            self._context = dict(context)
            _ = checkpoint_digest(self._context, "0" * 32)
            if not isinstance(backup_key_base64, str):
                raise ValueError("key must be str")
            raw_key = base64.b64decode(backup_key_base64.encode("ascii"), validate=True)
            if len(raw_key) != 32 or base64.b64encode(raw_key).decode("ascii") != backup_key_base64:
                raise ValueError("canonical base64 32 bytes required")
            self._backup_key = backup_key_base64
            euid = os.geteuid()
            for path, allow_exec in ((node_executable, True), (backup_cli_path, False)):
                if not isinstance(path, str) or not os.path.isabs(path) or os.path.normpath(path) != path or os.path.realpath(path) != path:
                    raise ValueError("non-canonical path")
                st = os.stat(path, follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    raise ValueError("not regular file")
                if st.st_uid not in (0, euid):
                    raise ValueError("invalid owner")
                mode = stat.S_IMODE(st.st_mode)
                if mode & 0o022 != 0:
                    raise ValueError("group/other writable")
                if not allow_exec and (mode & 0o111 != 0):
                    raise ValueError("cli must not be executable")
                if allow_exec and not os.access(path, os.X_OK):
                    raise ValueError("node not executable")
            self._resource_identity = {path: self._file_identity(os.lstat(path)) for path in (node_executable, backup_cli_path)}
            self._node = node_executable
            self._cli = backup_cli_path
            self._supervisor = supervisor
            root = supervisor._data_dir
            if not isinstance(root, str) or not os.path.isabs(root) or os.path.normpath(root) != root or os.path.realpath(root) != root:
                raise ValueError("non-canonical data_dir")
            st_root = os.stat(root, follow_symlinks=False)
            if not stat.S_ISDIR(st_root.st_mode) or stat.S_IMODE(st_root.st_mode) != 0o700 or st_root.st_uid != euid:
                raise ValueError("invalid data_dir attributes")
            self._root_identity = (st_root.st_dev, st_root.st_ino, st_root.st_uid, stat.S_IMODE(st_root.st_mode))
            self._root = root
            self._journal = LocalJobJournal(str(root))
            self._intents = RestoreIntentStore(str(root), self._context)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError("Management operation held") from None

    @staticmethod
    def _file_identity(value):
        return (value.st_dev, value.st_ino, value.st_uid, value.st_mode,
                value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def _verify_resources(self):
        try:
            if os.path.realpath(self._root) != self._root:
                raise ValueError("Root changed")
            value = os.lstat(self._root)
            if (value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)) != self._root_identity:
                raise ValueError("Root changed")
            for path, identity in self._resource_identity.items():
                if os.path.realpath(path) != path or self._file_identity(os.lstat(path)) != identity:
                    raise ValueError("Executable resource changed")
        except Exception:
            raise RuntimeError("Management operation held") from None

    def _run_cli(self, mode, in_leaf, out_leaf):
        self._verify_resources()
        env = {
            "SG_BACKUP_ROOT": self._root,
            "SG_BACKUP_KEY": self._backup_key,
            "SG_BACKUP_IMAGE": self._context["imageDigest"],
            "SG_BACKUP_KEY_ID": self._context["keyId"]
        }
        output = run_bounded([self._node, self._cli, mode, in_leaf, out_leaf], env, timeout=15, max_output=4096)
        self._verify_resources()
        data = json.loads(output.decode("utf-8"))
        if set(data.keys()) != {"mode", "output", "bytes", "sha256"}:
            raise ValueError("invalid response keys")
        if data["mode"] != mode or data["output"] != out_leaf or not isinstance(data["sha256"], str) or len(data["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in data["sha256"]):
            raise ValueError("invalid response values")
        b_cnt = data["bytes"]
        if type(b_cnt) is not int or b_cnt <= 0:
            raise ValueError("invalid bytes type/val")
        limit = MAX_ENCRYPTED_BYTES if mode == "encrypt" else MAX_SNAPSHOT_BYTES
        if b_cnt > limit:
            raise ValueError("size exceeded")
        return data

    def checkpoint(self, payload):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Management operation held")
        try:
            val = validate_checkpoint(self._context, payload)
            self._verify_resources()
            job_id, digest = val["job_id"], val["request_digest"]
            rec = self._journal.prepare(job_id, digest)
            if rec.get("state") == "artifact-verified":
                return rec
            if rec.get("state") != "prepared":
                raise RuntimeError("journal prepare failed")
            enc_leaf = f"sg-encrypted-{job_id}.bin"
            r_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    os.stat(enc_leaf, dir_fd=r_fd, follow_symlinks=False)
                    raise RuntimeError("encrypted file already exists")
                except FileNotFoundError:
                    pass
            finally:
                os.close(r_fd)
            snap_leaf = f"sg-snapshot-{secrets.token_hex(16)}.sqlite"
            snap_meta = write_bounded_snapshot(self._supervisor, snap_leaf, max_bytes=MAX_SNAPSHOT_BYTES, timeout=10)
            if snap_meta.get("leaf") != snap_leaf:
                raise RuntimeError("snapshot leaf mismatch")
            cli_res = self._run_cli("encrypt", snap_leaf, enc_leaf)
            return self._journal.record_artifact(job_id, digest, enc_leaf, cli_res["bytes"], cli_res["sha256"])
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError("Management operation held") from None
        finally:
            self._lock.release()

    def restore(self, payload):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Management operation held")
        try:
            v = validate_restore(self._context, payload)
            self._verify_resources()
            s_id, s_dig = v["source_checkpoint_job_id"], v["source_request_digest"]
            rec = self._journal.reconcile(s_id, s_dig)
            if rec.get("state") != "artifact-verified":
                raise RuntimeError("source not verified")
            art = rec.get("artifact", {})
            if (art.get("leaf") != v["leaf"] or art.get("bytes") != v["bytes"] or
                art.get("sha256") != v["sha256"] or s_dig != checkpoint_digest(self._context, s_id)):
                raise RuntimeError("source artifact mismatch")
            st = self._intents.prepare(payload)
            if st.get("state") == "completed-local":
                return {**st, "historical": True}
            if st.get("state") != "prepared":
                raise RuntimeError("intent prepare held")
            plain_leaf = f"sg-restore-plain-{v['restore_job_id']}-{secrets.token_hex(8)}.sqlite"
            cli_res = self._run_cli("decrypt", v["leaf"], plain_leaf)
            r_fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                st_r_pre = os.fstat(r_fd)
                f_fd = os.open(plain_leaf, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=r_fd)
                try:
                    st1 = os.fstat(f_fd)
                    if not stat.S_ISREG(st1.st_mode) or stat.S_IMODE(st1.st_mode) != 0o600 or st1.st_nlink != 1 or st1.st_uid != os.geteuid():
                        raise RuntimeError("bad file mode/owner")
                    if st1.st_size <= 0 or st1.st_size > MAX_SNAPSHOT_BYTES or st1.st_size != cli_res["bytes"]:
                        raise RuntimeError("size mismatch")
                    buf = bytearray()
                    while len(buf) < MAX_SNAPSHOT_BYTES + 1:
                        chunk = os.read(f_fd, 65536)
                        if not chunk:
                            break
                        buf.extend(chunk)
                    if len(buf) > MAX_SNAPSHOT_BYTES or len(buf) != st1.st_size:
                        raise RuntimeError("read size mismatch")
                    st2 = os.fstat(f_fd)
                    st_named = os.stat(plain_leaf, dir_fd=r_fd, follow_symlinks=False)
                    st_r_post = os.fstat(r_fd)
                    if (st1.st_dev != st2.st_dev or st1.st_ino != st2.st_ino or
                        st1.st_mtime_ns != st2.st_mtime_ns or st1.st_ctime_ns != st2.st_ctime_ns or
                        st_named.st_dev != st1.st_dev or st_named.st_ino != st1.st_ino or
                        st_r_pre.st_dev != st_r_post.st_dev or st_r_pre.st_ino != st_r_post.st_ino):
                        raise RuntimeError("inode/ns validation failed")
                    raw_bytes = bytes(buf)
                    if not raw_bytes.startswith(SQLITE_HEADER) or hashlib.sha256(raw_bytes).hexdigest() != cli_res["sha256"]:
                        raise RuntimeError("content validation failed")
                finally:
                    os.close(f_fd)
            finally:
                os.close(r_fd)
            rec2 = self._journal.reconcile(s_id, s_dig)
            if rec2.get("state") != "artifact-verified" or rec2.get("artifact") != art:
                raise RuntimeError("source changed during decrypt")
            self._verify_resources()
            tok = self._intents.begin_mutation(payload)
            self._supervisor.restore(raw_bytes)
            health_deadline = time.monotonic() + 10.0
            while True:
                healthy = self._supervisor._check_http_health()
                if time.monotonic() >= health_deadline:
                    raise RuntimeError("health deadline exceeded")
                if healthy:
                    break
                time.sleep(min(0.1, max(0.0, health_deadline - time.monotonic())))
            return self._intents.complete(payload, tok, health_verified=True)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError("Management operation held") from None
        finally:
            self._lock.release()

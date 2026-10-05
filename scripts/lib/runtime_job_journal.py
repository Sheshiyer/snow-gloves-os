"""Linux-only Local Job Journal implementation."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import sys

_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_LEAF_RE = re.compile(r"^sg-encrypted-[0-9a-f]{32}\.bin$")
_MAX_ARTIFACT_SIZE = 64 * 1024 * 1024 + 4136
_MAX_JOURNAL_SIZE = 2048


def _validate_job_id(v: str) -> None:
    if not isinstance(v, str) or not _HEX32_RE.fullmatch(v):
        raise RuntimeError("Local job held")


def _validate_digest(v: str) -> None:
    if not isinstance(v, str) or not _HEX64_RE.fullmatch(v):
        raise RuntimeError("Local job held")


def _validate_leaf(v: str) -> None:
    if not isinstance(v, str) or not _LEAF_RE.fullmatch(v):
        raise RuntimeError("Local job held")


def _validate_size(v: int) -> None:
    if type(v) is not int or v <= 0 or v > _MAX_ARTIFACT_SIZE:
        raise RuntimeError("Local job held")


def _no_dup_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    d: dict[str, object] = {}
    for k, v in pairs:
        if k in d:
            raise RuntimeError("Local job held")
        d[k] = v
    return d


def _parse_and_validate_record(raw: bytes) -> dict[str, object]:
    if len(raw) > _MAX_JOURNAL_SIZE:
        raise RuntimeError("Local job held")
    try:
        text = raw.decode("utf-8")
        d = json.loads(text, object_pairs_hook=_no_dup_pairs)
    except Exception:
        raise RuntimeError("Local job held")

    if not isinstance(d, dict):
        raise RuntimeError("Local job held")
    expected_keys = {"schema", "job_id", "request_digest", "state", "artifact"}
    if set(d.keys()) != expected_keys:
        raise RuntimeError("Local job held")

    if d["schema"] != "sg.local-job.v1":
        raise RuntimeError("Local job held")
    _validate_job_id(d["job_id"])
    _validate_digest(d["request_digest"])

    state = d["state"]
    if state not in ("prepared", "artifact-verified"):
        raise RuntimeError("Local job held")

    art = d["artifact"]
    if state == "prepared":
        if art is not None:
            raise RuntimeError("Local job held")
    else:
        if not isinstance(art, dict):
            raise RuntimeError("Local job held")
        if set(art.keys()) != {"leaf", "bytes", "sha256"}:
            raise RuntimeError("Local job held")
        _validate_leaf(art["leaf"])
        _validate_size(art["bytes"])
        _validate_digest(art["sha256"])

    canonical_raw = json.dumps(
        {
            "schema": d["schema"],
            "job_id": d["job_id"],
            "request_digest": d["request_digest"],
            "state": d["state"],
            "artifact": (
                None
                if d["artifact"] is None
                else {
                    "leaf": d["artifact"]["leaf"],
                    "bytes": d["artifact"]["bytes"],
                    "sha256": d["artifact"]["sha256"],
                }
            ),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    if raw != canonical_raw:
        raise RuntimeError("Local job held")

    return {
        "schema": "sg.local-job.v1",
        "job_id": d["job_id"],
        "request_digest": d["request_digest"],
        "state": d["state"],
        "artifact": (
            None
            if d["artifact"] is None
            else {
                "leaf": d["artifact"]["leaf"],
                "bytes": d["artifact"]["bytes"],
                "sha256": d["artifact"]["sha256"],
            }
        ),
    }


def _serialize_record(rec: dict[str, object]) -> bytes:
    d = {
        "schema": "sg.local-job.v1",
        "job_id": rec["job_id"],
        "request_digest": rec["request_digest"],
        "state": rec["state"],
        "artifact": (
            None
            if rec["artifact"] is None
            else {
                "leaf": rec["artifact"]["leaf"],
                "bytes": rec["artifact"]["bytes"],
                "sha256": rec["artifact"]["sha256"],
            }
        ),
    }
    return json.dumps(d, separators=(",", ":")).encode("utf-8")


class LocalJobJournal:
    def __init__(self, root_path: str) -> None:
        if not isinstance(root_path, str) or not os.path.isabs(root_path):
            raise RuntimeError("Local job held")
        if sys.platform != "linux" or os.path.realpath(root_path) != root_path or os.path.normpath(root_path) != root_path:
            raise RuntimeError("Local job held")
        self._root_path = root_path

    def _check_root_stat(self, st: os.stat_result) -> None:
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError("Local job held")
        if (st.st_mode & 0o777) != 0o700:
            raise RuntimeError("Local job held")
        if st.st_uid != os.getuid():
            raise RuntimeError("Local job held")

    def _verify_root_unmoved(self, root_fd: int) -> None:
        if os.path.realpath(self._root_path) != self._root_path:
            raise RuntimeError("Local job held")
        fd_st = os.fstat(root_fd)
        self._check_root_stat(fd_st)
        p_st = os.stat(self._root_path, follow_symlinks=False)
        if (p_st.st_dev, p_st.st_ino) != (fd_st.st_dev, fd_st.st_ino):
            raise RuntimeError("Local job held")

    def _read_journal(self, root_fd: int, jname: str) -> tuple[dict[str, object], os.stat_result] | None:
        try:
            fd = os.open(jname, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=root_fd)
        except FileNotFoundError:
            return None
        except Exception:
            raise RuntimeError("Local job held")
        try:
            st1 = os.fstat(fd)
            if not stat.S_ISREG(st1.st_mode) or (st1.st_mode & 0o777) != 0o600 or st1.st_nlink != 1:
                raise RuntimeError("Local job held")
            if st1.st_uid != os.getuid() or st1.st_size > _MAX_JOURNAL_SIZE:
                raise RuntimeError("Local job held")
            raw = b""
            while True:
                chunk = os.read(fd, 2049)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 2048:
                    raise RuntimeError("Local job held")
            st2 = os.fstat(fd)
            if (st1.st_ino, st1.st_size, st1.st_mtime_ns, st1.st_ctime_ns) != (
                st2.st_ino, st2.st_size, st2.st_mtime_ns, st2.st_ctime_ns
            ):
                raise RuntimeError("Local job held")
            rec = _parse_and_validate_record(raw)
            return rec, st2
        finally:
            os.close(fd)

    def _verify_artifact_file(
        self, root_fd: int, leaf: str, expected_size: int, expected_sha: str
    ) -> None:
        _validate_leaf(leaf)
        _validate_size(expected_size)
        _validate_digest(expected_sha)
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=root_fd)
        except Exception:
            raise RuntimeError("Local job held")
        try:
            st1 = os.fstat(fd)
            if not stat.S_ISREG(st1.st_mode) or (st1.st_mode & 0o777) != 0o600 or st1.st_nlink != 1:
                raise RuntimeError("Local job held")
            if st1.st_uid != os.getuid() or st1.st_size != expected_size:
                raise RuntimeError("Local job held")
            hasher = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise RuntimeError("Local job held")
                hasher.update(chunk)
            if total != expected_size or hasher.hexdigest() != expected_sha:
                raise RuntimeError("Local job held")
            st2 = os.fstat(fd)
            if (st1.st_ino, st1.st_size, st1.st_mtime_ns, st1.st_ctime_ns) != (
                st2.st_ino, st2.st_size, st2.st_mtime_ns, st2.st_ctime_ns
            ):
                raise RuntimeError("Local job held")
        finally:
            os.close(fd)

    def _write_temp_journal(self, root_fd: int, content: bytes) -> tuple[str, int]:
        tmp_name = f".tmp-journal-{os.urandom(16).hex()}"
        try:
            fd = os.open(
                tmp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=root_fd,
            )
        except Exception:
            raise RuntimeError("Local job held")
        try:
            st1 = os.fstat(fd)
            if (st1.st_mode & 0o777) != 0o600 or st1.st_uid != os.getuid():
                raise RuntimeError("Local job held")
            view = memoryview(content)
            while len(view) > 0:
                nw = os.write(fd, view)
                if nw <= 0:
                    raise RuntimeError("Local job held")
                view = view[nw:]
            os.fsync(fd)
            st2 = os.fstat(fd)
            if st2.st_ino != st1.st_ino or st2.st_size != len(content):
                raise RuntimeError("Local job held")
            return tmp_name, st2.st_ino
        except Exception:
            st = os.fstat(fd)
            self._cleanup_temp(root_fd, tmp_name, st.st_ino, content)
            raise RuntimeError("Local job held") from None
        finally:
            os.close(fd)

    def _verify_temp(self, root_fd, name, inode, content):
        existing = self._read_journal(root_fd, name)
        if existing is None or existing[1].st_ino != inode or _serialize_record(existing[0]) != content:
            raise RuntimeError("Local job held")
        self._verify_root_unmoved(root_fd)

    def _cleanup_temp(self, root_fd: int, tmp_name: str, expected_ino: int, content: bytes) -> None:
        try:
            actual = self._read_journal(root_fd, tmp_name)
            if actual is None or _serialize_record(actual[0]) != content:
                return
            st = os.stat(tmp_name, dir_fd=root_fd, follow_symlinks=False)
            if stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_ino == expected_ino:
                os.unlink(tmp_name, dir_fd=root_fd)
        except Exception:
            pass

    def _run_op(self, fn):
        try:
            root_fd = os.open(self._root_path, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except Exception:
            raise RuntimeError("Local job held")
        try:
            self._check_root_stat(os.fstat(root_fd))
            try:
                fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except Exception:
                raise RuntimeError("Local job held")
            self._verify_root_unmoved(root_fd)
            return fn(root_fd)
        except Exception:
            raise RuntimeError("Local job held") from None
        finally:
            os.close(root_fd)

    def prepare(self, job_id: str, request_digest: str) -> dict[str, object]:
        _validate_job_id(job_id)
        _validate_digest(request_digest)

        def _op(root_fd: int) -> dict[str, object]:
            jname = f"sg-job-{job_id}.json"
            existing = self._read_journal(root_fd, jname)
            if existing is not None:
                rec, _ = existing
                if rec["job_id"] != job_id or rec["request_digest"] != request_digest:
                    raise RuntimeError("Local job held")
                if rec["state"] == "artifact-verified":
                    art = rec["artifact"]
                    self._verify_artifact_file(root_fd, art["leaf"], art["bytes"], art["sha256"])
                self._verify_root_unmoved(root_fd)
                return json.loads(json.dumps(rec))

            new_rec = {
                "schema": "sg.local-job.v1",
                "job_id": job_id,
                "request_digest": request_digest,
                "state": "prepared",
                "artifact": None,
            }
            content = _serialize_record(new_rec)
            tmp_name, tmp_ino = self._write_temp_journal(root_fd, content)
            try:
                self._verify_temp(root_fd, tmp_name, tmp_ino, content)
                try:
                    _publish_new(root_fd, tmp_name, jname)
                except Exception:
                    raise RuntimeError("Local job held")
            finally:
                self._cleanup_temp(root_fd, tmp_name, tmp_ino, content)

            try:
                os.fsync(root_fd)
                actual = self._read_journal(root_fd, jname)
                if actual is None or actual[1].st_ino != tmp_ino or actual[0] != new_rec:
                    raise RuntimeError("Local job held")
                if new_rec["artifact"] is not None:
                    art = new_rec["artifact"]
                    self._verify_artifact_file(root_fd, art["leaf"], art["bytes"], art["sha256"])
                self._verify_root_unmoved(root_fd)
            except Exception:
                raise RuntimeError("Local job held")
            return json.loads(json.dumps(new_rec))

        return self._run_op(_op)

    def record_artifact(
        self, job_id: str, request_digest: str, leaf: str, size: int, sha256: str
    ) -> dict[str, object]:
        _validate_job_id(job_id)
        _validate_digest(request_digest)
        _validate_leaf(leaf)
        _validate_size(size)
        _validate_digest(sha256)

        def _op(root_fd: int) -> dict[str, object]:
            jname = f"sg-job-{job_id}.json"
            existing = self._read_journal(root_fd, jname)
            if existing is None:
                raise RuntimeError("Local job held")
            rec, old_st = existing
            if rec["job_id"] != job_id or rec["request_digest"] != request_digest:
                raise RuntimeError("Local job held")

            self._verify_artifact_file(root_fd, leaf, size, sha256)

            if rec["state"] == "artifact-verified":
                art = rec["artifact"]
                if (art["leaf"], art["bytes"], art["sha256"]) != (leaf, size, sha256):
                    raise RuntimeError("Local job held")
                self._verify_root_unmoved(root_fd)
                return json.loads(json.dumps(rec))

            if rec["state"] != "prepared":
                raise RuntimeError("Local job held")

            new_rec = {
                "schema": "sg.local-job.v1",
                "job_id": job_id,
                "request_digest": request_digest,
                "state": "artifact-verified",
                "artifact": {"leaf": leaf, "bytes": size, "sha256": sha256},
            }
            content = _serialize_record(new_rec)
            tmp_name, tmp_ino = self._write_temp_journal(root_fd, content)
            try:
                cur = self._read_journal(root_fd, jname)
                if cur is None:
                    raise RuntimeError("Local job held")
                current_record, cur_st = cur
                if current_record != rec or (cur_st.st_dev,cur_st.st_ino,cur_st.st_size,cur_st.st_mtime_ns,cur_st.st_ctime_ns) != (old_st.st_dev,old_st.st_ino,old_st.st_size,old_st.st_mtime_ns,old_st.st_ctime_ns):
                    raise RuntimeError("Local job held")
                self._verify_temp(root_fd, tmp_name, tmp_ino, content)
                self._verify_artifact_file(root_fd, leaf, size, sha256)
                try:
                    os.rename(tmp_name, jname, src_dir_fd=root_fd, dst_dir_fd=root_fd)
                except Exception:
                    raise RuntimeError("Local job held")
            finally:
                self._cleanup_temp(root_fd, tmp_name, tmp_ino, content)

            try:
                os.fsync(root_fd)
                actual = self._read_journal(root_fd, jname)
                if actual is None or actual[1].st_ino != tmp_ino or actual[0] != new_rec:
                    raise RuntimeError("Local job held")
                if new_rec["artifact"] is not None:
                    art = new_rec["artifact"]
                    self._verify_artifact_file(root_fd, art["leaf"], art["bytes"], art["sha256"])
                self._verify_root_unmoved(root_fd)
            except Exception:
                raise RuntimeError("Local job held")
            return json.loads(json.dumps(new_rec))

        return self._run_op(_op)

    def reconcile(self, job_id: str, request_digest: str) -> dict[str, object]:
        _validate_job_id(job_id)
        _validate_digest(request_digest)

        def _op(root_fd: int) -> dict[str, object]:
            jname = f"sg-job-{job_id}.json"
            existing = self._read_journal(root_fd, jname)
            if existing is None:
                raise RuntimeError("Local job held")
            rec, _ = existing
            if rec["job_id"] != job_id or rec["request_digest"] != request_digest:
                raise RuntimeError("Local job held")
            if rec["state"] == "artifact-verified":
                art = rec["artifact"]
                self._verify_artifact_file(root_fd, art["leaf"], art["bytes"], art["sha256"])
            self._verify_root_unmoved(root_fd)
            return json.loads(json.dumps(rec))

        return self._run_op(_op)

import ctypes
import ctypes.util

RENAME_NOREPLACE = 1


def _validate_name(name: str) -> bytes:
    if not isinstance(name, str) or not name:
        raise RuntimeError("Local job held")
    if len(name) > 128 or "/" in name or "\x00" in name or name in (".", ".."):
        raise RuntimeError("Local job held")
    try:
        return name.encode("ascii")
    except UnicodeEncodeError:
        raise RuntimeError("Local job held") from None


def _publish_new(root_fd: int, temp_name: str, journal_name: str) -> None:
    if isinstance(root_fd, bool) or not isinstance(root_fd, int) or not 0 <= root_fd <= 2147483647:
        raise RuntimeError("Local job held")

    b_temp = _validate_name(temp_name)
    b_journal = _validate_name(journal_name)

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2")
    except Exception:
        raise RuntimeError("Local job held") from None

    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int

    res = renameat2(
        root_fd,
        b_temp,
        root_fd,
        b_journal,
        RENAME_NOREPLACE,
    )

    if res != 0:
        raise RuntimeError("Local job held") from None

import os
import sys
import stat
import time
import re
from dataclasses import dataclass

_SNAPSHOT_RE = re.compile(r"^sg-snapshot-[0-9a-f]{32}\.sqlite$")
_ENCRYPTED_RE = re.compile(r"^sg-encrypted-[0-9a-f]{32}\.bin$")
_PLAIN_RE = re.compile(r"^sg-restore-plain-[0-9a-f]{32}-[0-9a-f]{16}\.sqlite$")
_RECOVERY_RE = re.compile(r"^\.sg-recovery-[A-Za-z0-9_-]+\.sqlite$")
_JOURNAL_RE = re.compile(r"^sg-job-[0-9a-f]{32}\.json$")
_INTENT_RE = re.compile(r"^sg-restore-[0-9a-f]{32}\.json$")

CHECKPOINT_BYTE_RES = 134217728 + 4136 + 32768
RESTORE_BYTE_RES = 268435456 + 32768
PROJECTED_ENTRIES_RES = 8

_STAGE_SPECS = {
    "checkpoint": (134217728 + 4136 + 32768, 8, 1, 1, 0, 0, 1, 0),
    "checkpoint_snapshot": (134217728 + 4136 + 32768, 7, 1, 1, 0, 0, 0, 0),
    "checkpoint_encrypt": (67108864 + 4136 + 32768, 4, 0, 1, 0, 0, 0, 0),
    "restore": (268435456 + 32768, 8, 0, 0, 1, 1, 0, 1),
    "restore_decrypt": (268435456 + 32768, 7, 0, 0, 1, 1, 0, 0),
    "restore_mutate": (201326592 + 32768, 6, 0, 0, 0, 1, 0, 0),
}


@dataclass(frozen=True)
class StorageBudget:
    max_root_bytes: int = 536870912
    max_entries: int = 256
    max_depth: int = 3
    timeout_ms: int = 500
    min_free_bytes: int = 134217728
    max_snapshots: int = 32
    max_encrypted: int = 32
    max_plain_restores: int = 32
    max_recovery: int = 8
    max_journals: int = 64
    max_intents: int = 64

    def __post_init__(self):
        self._validate()

    def _validate(self):
        for field, (min_v, max_v) in [
            ("max_root_bytes", (1, 4 * 1024 * 1024 * 1024)),
            ("max_entries", (1, 4096)),
            ("max_depth", (1, 8)),
            ("timeout_ms", (1, 5000)),
            ("min_free_bytes", (1, 4 * 1024 * 1024 * 1024)),
            ("max_snapshots", (1, 512)),
            ("max_encrypted", (1, 512)),
            ("max_plain_restores", (1, 512)),
            ("max_recovery", (1, 128)),
            ("max_journals", (1, 512)),
            ("max_intents", (1, 512)),
        ]:
            v = getattr(self, field, None)
            if type(v) is not int or isinstance(v, bool):
                raise RuntimeError("Storage admission held")
            if v < min_v or v > max_v:
                raise RuntimeError("Storage admission held")


def _check_exact_int(val, min_v=0):
    if type(val) is not int or isinstance(val, bool) or val < min_v:
        raise RuntimeError("Storage admission held")


def _preflight(root: str, expected_identity: tuple, operation: str, budget: StorageBudget) -> dict:
    if sys.platform != "linux":
        raise RuntimeError("Storage admission held")
    if type(budget) is not StorageBudget:
        raise RuntimeError("Storage admission held")
    budget._validate()
    if operation not in _STAGE_SPECS:
        raise RuntimeError("Storage admission held")
    if type(expected_identity) is not tuple or len(expected_identity) != 4:
        raise RuntimeError("Storage admission held")
    exp_dev, exp_ino, exp_uid, exp_mode = expected_identity
    _check_exact_int(exp_dev, 1)
    _check_exact_int(exp_ino, 1)
    _check_exact_int(exp_uid, 0)
    _check_exact_int(exp_mode, 0)
    if exp_mode != 0o700:
        raise RuntimeError("Storage admission held")
    try:
        if exp_uid != os.geteuid():
            raise RuntimeError("Storage admission held")
    except Exception:
        raise RuntimeError("Storage admission held")

    if type(root) is not str or not os.path.isabs(root):
        raise RuntimeError("Storage admission held")

    start_time = time.monotonic()
    deadline = start_time + (budget.timeout_ms / 1000.0)

    def check_time():
        if time.monotonic() >= deadline:
            raise RuntimeError("Storage admission held")

    check_time()
    try:
        if os.path.realpath(root) != root:
            raise RuntimeError("Storage admission held")
        cur = root
        while True:
            check_time()
            if os.path.islink(cur):
                raise RuntimeError("Storage admission held")
            p = os.path.dirname(cur)
            if p == cur:
                break
            cur = p
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Storage admission held")

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        root_fd = os.open(root, flags)
    except Exception:
        raise RuntimeError("Storage admission held")

    try:
        check_time()
        try:
            st_root = os.fstat(root_fd)
        except Exception:
            raise RuntimeError("Storage admission held")

        if not stat.S_ISDIR(st_root.st_mode):
            raise RuntimeError("Storage admission held")
        root_mode = stat.S_IMODE(st_root.st_mode)
        if (st_root.st_dev != exp_dev or st_root.st_ino != exp_ino or
                st_root.st_uid != exp_uid or root_mode != exp_mode):
            raise RuntimeError("Storage admission held")
        if (st_root.st_mode & 0o7000) != 0:
            raise RuntimeError("Storage admission held")

        try:
            vfs = os.fstatvfs(root_fd)
        except Exception:
            raise RuntimeError("Storage admission held")

        _check_exact_int(vfs.f_frsize, 1)
        _check_exact_int(vfs.f_bavail, 0)
        avail_bytes = vfs.f_bavail * vfs.f_frsize

        req_res_bytes, req_entries_res, d_snap, d_enc, d_plain, d_rec, d_jrnl, d_int = _STAGE_SPECS[operation]
        if avail_bytes < budget.min_free_bytes + req_res_bytes:
            raise RuntimeError("Storage admission held")

        total_entries = 0
        total_counted_bytes = max(st_root.st_size, st_root.st_blocks * 512)
        if total_counted_bytes > budget.max_root_bytes:
            raise RuntimeError("Storage admission held")

        class_counts = {
            "snapshots": 0,
            "encrypted": 0,
            "plain_restores": 0,
            "recovery": 0,
            "journals": 0,
            "intents": 0,
        }
        recorded_files = []
        def metadata(st):
            return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_nlink,
                    st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_blocks)
        directory_metadata = {(): metadata(st_root)}

        def scan_dir(dir_fd, current_depth, parts=()):
            nonlocal total_entries, total_counted_bytes
            check_time()
            if current_depth > budget.max_depth:
                raise RuntimeError("Storage admission held")

            try:
                scanner = os.scandir(dir_fd)
            except Exception:
                raise RuntimeError("Storage admission held")

            with scanner:
                while True:
                    check_time()
                    try:
                        entry = next(scanner, None)
                    except Exception:
                        raise RuntimeError("Storage admission held")
                    if entry is None:
                        break

                    total_entries += 1
                    if total_entries > budget.max_entries:
                        raise RuntimeError("Storage admission held")

                    name = entry.name
                    if current_depth == 1:
                        if _SNAPSHOT_RE.match(name):
                            class_counts["snapshots"] += 1
                        elif _ENCRYPTED_RE.match(name):
                            class_counts["encrypted"] += 1
                        elif _PLAIN_RE.match(name):
                            class_counts["plain_restores"] += 1
                        elif _RECOVERY_RE.match(name):
                            class_counts["recovery"] += 1
                        elif _JOURNAL_RE.match(name):
                            class_counts["journals"] += 1
                        elif _INTENT_RE.match(name):
                            class_counts["intents"] += 1

                    try:
                        st_named = os.lstat(name, dir_fd=dir_fd)
                    except Exception:
                        raise RuntimeError("Storage admission held")

                    if stat.S_ISLNK(st_named.st_mode):
                        raise RuntimeError("Storage admission held")
                    if (st_named.st_mode & 0o7000) != 0:
                        raise RuntimeError("Storage admission held")
                    if st_named.st_dev != exp_dev or st_named.st_uid != exp_uid:
                        raise RuntimeError("Storage admission held")

                    mode = stat.S_IMODE(st_named.st_mode)
                    if (mode & 0o022) != 0:
                        raise RuntimeError("Storage admission held")

                    if stat.S_ISDIR(st_named.st_mode):
                        if mode not in (0o700, 0o755):
                            raise RuntimeError("Storage admission held")
                        sub_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
                        try:
                            sub_fd = os.open(name, sub_flags, dir_fd=dir_fd)
                        except Exception:
                            raise RuntimeError("Storage admission held")
                        try:
                            st_sub = os.fstat(sub_fd)
                            if (st_sub.st_dev != st_named.st_dev or st_sub.st_ino != st_named.st_ino or
                                    st_sub.st_mode != st_named.st_mode or st_sub.st_uid != st_named.st_uid):
                                raise RuntimeError("Storage admission held")
                            allocated = max(st_sub.st_size, st_sub.st_blocks * 512)
                            total_counted_bytes += allocated
                            if total_counted_bytes > budget.max_root_bytes:
                                raise RuntimeError("Storage admission held")
                            directory_metadata[parts + (name,)] = metadata(st_sub)
                            recorded_files.append((parts + (name,), metadata(st_sub)))
                            scan_dir(sub_fd, current_depth + 1, parts + (name,))
                            if metadata(os.fstat(sub_fd)) != metadata(st_sub):
                                raise RuntimeError('Storage admission held')
                        finally:
                            try:
                                os.close(sub_fd)
                            except Exception:
                                pass
                    elif stat.S_ISREG(st_named.st_mode):
                        if mode not in (0o600, 0o644):
                            raise RuntimeError("Storage admission held")
                        if st_named.st_nlink != 1:
                            raise RuntimeError("Storage admission held")
                        reg_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
                        try:
                            file_fd = os.open(name, reg_flags, dir_fd=dir_fd)
                        except Exception:
                            raise RuntimeError("Storage admission held")
                        try:
                            st_file = os.fstat(file_fd)
                            if (st_file.st_dev != st_named.st_dev or st_file.st_ino != st_named.st_ino or
                                    st_file.st_mode != st_named.st_mode or st_file.st_uid != st_named.st_uid or
                                    st_file.st_nlink != st_named.st_nlink or st_file.st_size != st_named.st_size or
                                    st_file.st_mtime_ns != st_named.st_mtime_ns or st_file.st_ctime_ns != st_named.st_ctime_ns or
                                    st_file.st_blocks != st_named.st_blocks):
                                raise RuntimeError("Storage admission held")
                        finally:
                            try:
                                os.close(file_fd)
                            except Exception:
                                pass

                        try:
                            st_after = os.lstat(name, dir_fd=dir_fd)
                            if (st_after.st_dev != st_named.st_dev or st_after.st_ino != st_named.st_ino or
                                    st_after.st_mode != st_named.st_mode or st_after.st_uid != st_named.st_uid or
                                    st_after.st_nlink != st_named.st_nlink or st_after.st_size != st_named.st_size or
                                    st_after.st_mtime_ns != st_named.st_mtime_ns or st_after.st_ctime_ns != st_named.st_ctime_ns or
                                    st_after.st_blocks != st_named.st_blocks):
                                raise RuntimeError("Storage admission held")
                        except Exception:
                            raise RuntimeError("Storage admission held")

                        allocated = max(st_named.st_size, st_named.st_blocks * 512)
                        total_counted_bytes += allocated
                        if total_counted_bytes > budget.max_root_bytes:
                            raise RuntimeError("Storage admission held")
                        recorded_files.append((parts + (name,), metadata(st_named)))
                    else:
                        raise RuntimeError("Storage admission held")

        scan_dir(root_fd, 1)

        for parts, observed in recorded_files:
            check_time()
            parent = root_fd
            try:
                for depth, component in enumerate(parts[:-1], 1):
                    check_time()
                    nxt = os.open(component, flags, dir_fd=parent)
                    if parent != root_fd:
                        os.close(parent)
                    parent = nxt
                    if metadata(os.fstat(parent)) != directory_metadata[parts[:depth]]:
                        raise RuntimeError("Storage admission held")
                check_time()
                st_chk = os.lstat(parts[-1], dir_fd=parent)
                if metadata(st_chk) != observed:
                    raise RuntimeError("Storage admission held")
            except Exception:
                raise RuntimeError("Storage admission held") from None
            finally:
                if parent != root_fd:
                    os.close(parent)

        proj_snapshots = class_counts["snapshots"] + d_snap
        proj_encrypted = class_counts["encrypted"] + d_enc
        proj_plain = class_counts["plain_restores"] + d_plain
        proj_recovery = class_counts["recovery"] + d_rec
        proj_journals = class_counts["journals"] + d_jrnl
        proj_intents = class_counts["intents"] + d_int

        if proj_snapshots > budget.max_snapshots or \
           proj_encrypted > budget.max_encrypted or \
           proj_plain > budget.max_plain_restores or \
           proj_recovery > budget.max_recovery or \
           proj_journals > budget.max_journals or \
           proj_intents > budget.max_intents:
            raise RuntimeError("Storage admission held")

        if total_entries + req_entries_res > budget.max_entries:
            raise RuntimeError("Storage admission held")

        if total_counted_bytes + req_res_bytes > budget.max_root_bytes:
            raise RuntimeError("Storage admission held")

        check_time()
        try:
            vfs_final = os.fstatvfs(root_fd)
            _check_exact_int(vfs_final.f_frsize, 1)
            _check_exact_int(vfs_final.f_bavail, 0)
            avail_final = vfs_final.f_bavail * vfs_final.f_frsize
            if avail_final < budget.min_free_bytes + req_res_bytes:
                raise RuntimeError("Storage admission held")
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError("Storage admission held")

        try:
            final_named_st = os.stat(root, follow_symlinks=False)
            final_fd_st = os.fstat(root_fd)
        except Exception:
            raise RuntimeError("Storage admission held")

        if stat.S_ISLNK(final_named_st.st_mode):
            raise RuntimeError("Storage admission held")

        if (final_named_st.st_dev != exp_dev or final_named_st.st_ino != exp_ino or
                final_named_st.st_uid != exp_uid or stat.S_IMODE(final_named_st.st_mode) != exp_mode or
                (final_named_st.st_mode & 0o7000) != 0):
            raise RuntimeError("Storage admission held")
        if (final_fd_st.st_dev != exp_dev or final_fd_st.st_ino != exp_ino or
                final_fd_st.st_uid != exp_uid or stat.S_IMODE(final_fd_st.st_mode) != exp_mode or
                (final_fd_st.st_mode & 0o7000) != 0):
            raise RuntimeError("Storage admission held")

        if metadata(final_named_st) != metadata(st_root) or metadata(final_fd_st) != metadata(st_root):
            raise RuntimeError("Storage admission held")
        if os.path.realpath(root) != root:
            raise RuntimeError("Storage admission held")
        check_time()

        return {
            "counted_bytes": total_counted_bytes,
            "entries": total_entries,
            "available_bytes": avail_final,
            "projected_snapshots": proj_snapshots,
            "projected_encrypted": proj_encrypted,
            "projected_plain_restores": proj_plain,
            "projected_recovery": proj_recovery,
            "projected_journals": proj_journals,
            "projected_intents": proj_intents,
        }
    finally:
        try:
            os.close(root_fd)
        except Exception:
            pass


def preflight(root: str, expected_identity: tuple, operation: str, budget: StorageBudget) -> dict:
    try:
        if type(operation) is not str:
            raise RuntimeError("Storage admission held")
        return _preflight(root, expected_identity, operation, budget)
    except Exception:
        raise RuntimeError("Storage admission held") from None

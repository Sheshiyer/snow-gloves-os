"""Linux-only bounded snapshot helper for local SQLite runtime storage.

Finalized artifact safety model:
- SQLite online backup is executed in bounded batches (16 pages) against
  an exclusively created temporary snapshot file in the canonical runtime dir.
- SQLite page size and logical page counts are preflighted to guarantee that
  source logical size <= max_bytes before copying begins.
- Backup progress callbacks actively monitor monotonic deadlines and abort if
  source logical growth exceeds max_bytes, bounding overshoot to at most one small
  backup step.
- Final output size is bounded by max_bytes, verified with PRAGMA quick_check,
  hashed strictly in bounded 64KiB chunks via stable descriptor metadata, durably fsynced,
  and published via atomic hard link (os.link without clobbering).
"""

import errno
import hashlib
import math
import os
import re
import sqlite3
import stat
import sys
import time
import urllib.parse
import uuid

__all__ = ["write_bounded_snapshot"]

_LEAF_PATTERN = re.compile(r"^sg-snapshot-[0-9a-f]{32}\.sqlite$")
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _stat_canonical_dir(path: str) -> tuple[int, int, int, int]:
    resolved = os.path.realpath(path)
    if resolved != path or not os.path.isabs(path):
        raise RuntimeError("Runtime snapshot failed")

    # Walk parents and verify no component was a symlink
    curr = path
    while True:
        st_l = os.lstat(curr)
        if stat.S_ISLNK(st_l.st_mode):
            raise RuntimeError("Runtime snapshot failed")
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent

    st = os.stat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError("Runtime snapshot failed")
    if (st.st_mode & 0o777) != 0o700:
        raise RuntimeError("Runtime snapshot failed")
    if st.st_uid != os.geteuid():
        raise RuntimeError("Runtime snapshot failed")
    return st.st_dev, st.st_ino, st.st_uid, st.st_mode


def _verify_root_fd(root_fd: int, expected: tuple[int, int, int, int]) -> None:
    st = os.fstat(root_fd)
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError("Runtime snapshot failed")
    if (
        st.st_dev != expected[0]
        or st.st_ino != expected[1]
        or st.st_uid != expected[2]
        or (st.st_mode & 0o777) != 0o700
    ):
        raise RuntimeError("Runtime snapshot failed")


def _verify_source_db(root_fd: int) -> tuple[int, int, int]:
    # Verify regular storage.sqlite
    st = os.stat("storage.sqlite", dir_fd=root_fd, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode):
        raise RuntimeError("Runtime snapshot failed")
    if st.st_uid != os.geteuid():
        raise RuntimeError("Runtime snapshot failed")
    if (st.st_mode & 0o777) not in (0o600, 0o644):
        raise RuntimeError("Runtime snapshot failed")
    if st.st_nlink != 1:
        raise RuntimeError("Runtime snapshot failed")

    # Validate header bounded
    db_fd = os.open(
        f"/proc/self/fd/{root_fd}/storage.sqlite",
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        hdr = os.read(db_fd, 16)
        if hdr != _SQLITE_MAGIC:
            raise RuntimeError("Runtime snapshot failed")
    finally:
        os.close(db_fd)

    return st.st_dev, st.st_ino, st.st_size


def write_bounded_snapshot(
    supervisor,
    output_leaf: str,
    *,
    max_bytes: int = 67108864,
    timeout: float = 10.0,
) -> dict:
    if sys.platform != "linux":
        raise RuntimeError("Runtime snapshot failed")

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
        raise RuntimeError("Runtime snapshot failed")
    if max_bytes < 1 or max_bytes > 67108864:
        raise RuntimeError("Runtime snapshot failed")

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0.0
        or timeout > 30.0
        or math.isnan(timeout)
        or math.isinf(timeout)
    ):
        raise RuntimeError("Runtime snapshot failed")

    if not isinstance(output_leaf, str) or not _LEAF_PATTERN.fullmatch(output_leaf):
        raise RuntimeError("Runtime snapshot failed")

    deadline = time.monotonic() + timeout

    lock = getattr(supervisor, "_lock", None)
    if lock is None or not hasattr(lock, "acquire") or not hasattr(lock, "release"):
        raise RuntimeError("Runtime snapshot failed")

    lock_acquired = lock.acquire(blocking=True, timeout=max(0.001, deadline - time.monotonic()))
    if not lock_acquired:
        raise RuntimeError("Runtime snapshot failed")

    root_fd = -1
    temp_fd = -1
    temp_leaf = None
    temp_ident = None  # (dev, ino, uid)
    published_created = False
    src_conn = None
    dst_conn = None

    try:
        if time.monotonic() > deadline:
            raise RuntimeError("Runtime snapshot failed")

        preflight_fn = getattr(supervisor, "_preflight", None)
        if not callable(preflight_fn):
            raise RuntimeError("Runtime snapshot failed")
        preflight_fn()

        data_dir = getattr(supervisor, "_data_dir", None)
        db_path = getattr(supervisor, "_db_path", None)
        if not isinstance(data_dir, str) or not isinstance(db_path, str):
            raise RuntimeError("Runtime snapshot failed")

        if db_path != os.path.join(data_dir, "storage.sqlite"):
            raise RuntimeError("Runtime snapshot failed")

        root_ident = _stat_canonical_dir(data_dir)

        root_fd = os.open(
            data_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        _verify_root_fd(root_fd, root_ident)

        # Ensure output_leaf does not already exist
        try:
            os.stat(output_leaf, dir_fd=root_fd, follow_symlinks=False)
            raise RuntimeError("Runtime snapshot failed")
        except FileNotFoundError:
            pass
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError("Runtime snapshot failed")

        src_dev, src_ino, _ = _verify_source_db(root_fd)

        # Create exclusive temporary snapshot file
        temp_leaf = f".sg-snapshot-work-{uuid.uuid4().hex}.sqlite"
        temp_proc_path = f"/proc/self/fd/{root_fd}/{temp_leaf}"
        temp_fd = os.open(
            temp_proc_path,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        st_temp = os.fstat(temp_fd)
        if (st_temp.st_mode & 0o777) != 0o600 or st_temp.st_uid != os.geteuid():
            raise RuntimeError("Runtime snapshot failed")
        temp_ident = (st_temp.st_dev, st_temp.st_ino, st_temp.st_uid)

        # Verify root stability
        _verify_root_fd(root_fd, root_ident)

        # Source connection
        src_proc_path = f"/proc/self/fd/{root_fd}/storage.sqlite"
        encoded_src_path = urllib.parse.quote(src_proc_path, safe="/")
        src_uri = f"file:{encoded_src_path}?mode=ro&immutable=0"
        dst_uri = f"file:/proc/self/fd/{temp_fd}?mode=rw"

        busy_ms = max(1, int((deadline - time.monotonic()) * 1000))
        src_conn = sqlite3.connect(
            src_uri,
            uri=True,
            timeout=max(0.001, deadline - time.monotonic()),
            check_same_thread=False,
        )
        src_conn.execute(f"PRAGMA busy_timeout = {busy_ms}")

        cursor = src_conn.cursor()
        cursor.execute("PRAGMA page_size")
        row = cursor.fetchone()
        if not row or not isinstance(row[0], int) or row[0] < 512 or row[0] > 65536:
            raise RuntimeError("Runtime snapshot failed")
        src_page_size = row[0]

        cursor.execute("PRAGMA page_count")
        row = cursor.fetchone()
        if not row or not isinstance(row[0], int) or row[0] < 0:
            raise RuntimeError("Runtime snapshot failed")
        src_page_count = row[0]

        if src_page_count * src_page_size > max_bytes:
            raise RuntimeError("Runtime snapshot failed")

        dst_conn = sqlite3.connect(
            dst_uri,
            uri=True,
            timeout=max(0.001, deadline - time.monotonic()),
            check_same_thread=False,
        )
        dst_conn.execute(f"PRAGMA busy_timeout = {busy_ms}")

        def _backup_progress(status: int, remaining: int, total: int) -> None:
            if time.monotonic() > deadline:
                raise RuntimeError("Runtime snapshot failed")
            if total * src_page_size > max_bytes:
                raise RuntimeError("Runtime snapshot failed")

        with dst_conn:
            src_conn.backup(
                dst_conn,
                pages=16,
                progress=_backup_progress,
            )

        dst_conn.commit()
        # Only the completed scratch destination is normalized; source WAL remains live.
        checkpoint = dst_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and checkpoint[0] != 0:
            raise RuntimeError("Runtime snapshot failed")
        journal = dst_conn.execute("PRAGMA journal_mode=DELETE").fetchone()
        if journal is None or str(journal[0]).lower() != "delete":
            raise RuntimeError("Runtime snapshot failed")

        # Close connections before sidecar/quick_check and fsync
        src_conn.close()
        src_conn = None
        dst_conn.close()
        dst_conn = None

        # Run PRAGMA quick_check on temp snapshot
        check_conn = sqlite3.connect(dst_uri.replace("?mode=rw", "?mode=ro"), uri=True,
                                     timeout=max(0.001, deadline - time.monotonic()), check_same_thread=False)
        try:
            chk_cur = check_conn.cursor()
            chk_cur.execute("PRAGMA quick_check")
            chk_row = chk_cur.fetchone()
            if not chk_row or chk_row[0] != "ok":
                raise RuntimeError("Runtime snapshot failed")
        finally:
            check_conn.close()

        # Verify temp descriptor stability and final size
        st_final = os.fstat(temp_fd)
        if (
            st_final.st_dev != temp_ident[0]
            or st_final.st_ino != temp_ident[1]
            or st_final.st_uid != temp_ident[2]
            or (st_final.st_mode & 0o777) != 0o600
            or st_final.st_size <= 0
            or st_final.st_size > max_bytes
        ):
            raise RuntimeError("Runtime snapshot failed")

        # Compute SHA256 in 64KiB chunks directly from temp_fd
        hasher = hashlib.sha256()
        bytes_read = 0
        pos = 0
        while True:
            chunk = os.pread(temp_fd, 65536, pos)
            if not chunk:
                break
            bytes_read += len(chunk)
            if bytes_read > max_bytes:
                raise RuntimeError("Runtime snapshot failed")
            hasher.update(chunk)
            pos += len(chunk)

        if bytes_read != st_final.st_size:
            raise RuntimeError("Runtime snapshot failed")

        st_post_hash = os.fstat(temp_fd)
        if (
            st_post_hash.st_dev != st_final.st_dev
            or st_post_hash.st_ino != st_final.st_ino
            or st_post_hash.st_size != st_final.st_size
            or st_post_hash.st_mtime_ns != st_final.st_mtime_ns
        ):
            raise RuntimeError("Runtime snapshot failed")

        sha256_hex = hasher.hexdigest()

        # Flush temp file durably
        os.fsync(temp_fd)

        # Pre-publication preflight & root/source stability check
        preflight_fn()
        if _stat_canonical_dir(data_dir) != root_ident:
            raise RuntimeError("Runtime snapshot failed")
        _verify_root_fd(root_fd, root_ident)
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                os.stat(temp_leaf + suffix, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise RuntimeError("Runtime snapshot failed")
        current_temp = os.stat(temp_leaf, dir_fd=root_fd, follow_symlinks=False)
        if (not stat.S_ISREG(current_temp.st_mode) or
                (current_temp.st_dev, current_temp.st_ino, current_temp.st_uid) != temp_ident or
                current_temp.st_nlink != 1 or (current_temp.st_mode & 0o777) != 0o600):
            raise RuntimeError("Runtime snapshot failed")
        src_st_post = os.stat("storage.sqlite", dir_fd=root_fd, follow_symlinks=False)
        if src_st_post.st_dev != src_dev or src_st_post.st_ino != src_ino:
            raise RuntimeError("Runtime snapshot failed")

        # Atomic publish via linkat
        os.link(
            temp_leaf,
            output_leaf,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
        published_created = True

        # Verify published file identity and link count
        st_pub = os.stat(output_leaf, dir_fd=root_fd, follow_symlinks=False)
        if (
            st_pub.st_dev != temp_ident[0]
            or st_pub.st_ino != temp_ident[1]
            or st_pub.st_uid != os.geteuid()
            or (st_pub.st_mode & 0o777) != 0o600
            or st_pub.st_size != st_final.st_size
            or st_pub.st_nlink != 2
        ):
            raise RuntimeError("Runtime snapshot failed")

        # Verify the published bytes themselves, not only the buffered digest.
        published_fd = os.open(output_leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
        try:
            before = os.fstat(published_fd)
            if (before.st_dev, before.st_ino, before.st_uid) != temp_ident:
                raise RuntimeError("Runtime snapshot failed")
            published_hash = hashlib.sha256()
            count = 0
            while True:
                chunk = os.read(published_fd, min(65536, max_bytes + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes or time.monotonic() > deadline:
                    raise RuntimeError("Runtime snapshot failed")
                published_hash.update(chunk)
            after = os.fstat(published_fd)
            if (count != st_final.st_size or published_hash.hexdigest() != sha256_hex or
                    after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns or
                    after.st_ctime_ns != before.st_ctime_ns or after.st_nlink != 2):
                raise RuntimeError("Runtime snapshot failed")
        finally:
            os.close(published_fd)

        # Remove temporary link
        st_temp_pre_del = os.stat(temp_leaf, dir_fd=root_fd, follow_symlinks=False)
        if (
            st_temp_pre_del.st_dev == temp_ident[0]
            and st_temp_pre_del.st_ino == temp_ident[1]
            and st_temp_pre_del.st_uid == temp_ident[2]
        ):
            os.unlink(temp_leaf, dir_fd=root_fd)
            temp_leaf = None
        else:
            raise RuntimeError("Runtime snapshot failed")

        # Verify published nlink is now 1
        st_pub_final = os.stat(output_leaf, dir_fd=root_fd, follow_symlinks=False)
        if st_pub_final.st_nlink != 1:
            raise RuntimeError("Runtime snapshot failed")

        # Fsync directory to make directory entry changes durable
        os.fsync(root_fd)

        # Final checks
        preflight_fn()
        if _stat_canonical_dir(data_dir) != root_ident:
            raise RuntimeError("Runtime snapshot failed")
        _verify_root_fd(root_fd, root_ident)
        if time.monotonic() > deadline:
            raise RuntimeError("Runtime snapshot failed")

        return {
            "leaf": output_leaf,
            "bytes": st_final.st_size,
            "sha256": sha256_hex,
        }

    except (KeyboardInterrupt, SystemExit):
        # Owned cleanup before propagating control exception
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if temp_fd != -1:
            try:
                os.close(temp_fd)
            except Exception:
                pass
            temp_fd = -1
        if root_fd != -1 and temp_leaf is not None and temp_ident is not None:
            try:
                st_cur = os.stat(temp_leaf, dir_fd=root_fd, follow_symlinks=False)
                if (
                    st_cur.st_dev == temp_ident[0]
                    and st_cur.st_ino == temp_ident[1]
                    and st_cur.st_uid == temp_ident[2]
                ):
                    os.unlink(temp_leaf, dir_fd=root_fd)
            except Exception:
                pass
        raise
    except Exception:
        if src_conn is not None:
            try:
                src_conn.close()
            except Exception:
                pass
        if dst_conn is not None:
            try:
                dst_conn.close()
            except Exception:
                pass
        if temp_fd != -1:
            try:
                os.close(temp_fd)
            except Exception:
                pass
            temp_fd = -1
        if root_fd != -1 and temp_leaf is not None and temp_ident is not None:
            try:
                st_cur = os.stat(temp_leaf, dir_fd=root_fd, follow_symlinks=False)
                if (
                    st_cur.st_dev == temp_ident[0]
                    and st_cur.st_ino == temp_ident[1]
                    and st_cur.st_uid == temp_ident[2]
                ):
                    os.unlink(temp_leaf, dir_fd=root_fd)
            except Exception:
                pass
        raise RuntimeError("Runtime snapshot failed") from None
    finally:
        if temp_fd != -1:
            try:
                os.close(temp_fd)
            except Exception:
                pass
        if root_fd != -1:
            try:
                os.close(root_fd)
            except Exception:
                pass
        try:
            lock.release()
        except Exception:
            pass

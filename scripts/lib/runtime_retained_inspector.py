"""Linux-only Retained File Inspector implementation."""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import sys
import time
from typing import Any

from lib.runtime_job_journal import _parse_and_validate_record
from lib.runtime_operation_identity import checkpoint_digest, _val_context
from lib.runtime_restore_intent import RestoreIntentStore

_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_RE = re.compile(r"^sg-snapshot-[0-9a-f]{32}\.sqlite$")
_ENCRYPTED_RE = re.compile(r"^sg-encrypted-[0-9a-f]{32}\.bin$")
_PLAIN_RE = re.compile(r"^sg-restore-plain-[0-9a-f]{32}-[0-9a-f]{16}\.sqlite$")
_RECOVERY_RE = re.compile(r"^\.sg-recovery-[A-Za-z0-9_-]+\.sqlite$")
_JOURNAL_RE = re.compile(r"^sg-job-[0-9a-f]{32}\.json$")
_INTENT_RE = re.compile(r"^sg-restore-[0-9a-f]{32}\.json$")

_MAX_ROOT_BYTES = 536870912
_MAX_ENTRIES = 256
_MAX_DEPTH = 3
_TIMEOUT_SECONDS = 2.0
_MAX_RECORD_FILE_SIZE = 2048
_MAX_RECORD_TOTAL_BYTES = 1048576
_MAX_CIPHERTEXT_SIZE = 64 * 1024 * 1024 + 4136
_MAX_HASH_OPERATIONS = 64
_MAX_HASH_TOTAL_BYTES = _MAX_CIPHERTEXT_SIZE


class _BudgetExpired(Exception):
    pass


def _hold() -> None:
    raise RuntimeError("Retained inspection held") from None


def _stat_sig_blocks(st: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        st.st_dev,
        st.st_ino,
        st.st_mode,
        st.st_uid,
        st.st_nlink,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
        st.st_blocks,
    )


def _validate_root_path(root_path: str, deadline: float) -> str:
    if time.monotonic() >= deadline:
        raise _BudgetExpired()
    if sys.platform != "linux" or type(root_path) is not str or not os.path.isabs(root_path):
        _hold()
    if len(root_path.encode("utf-8", errors="surrogateescape")) > 4096:
        _hold()
    if os.path.realpath(root_path) != root_path or os.path.normpath(root_path) != root_path:
        _hold()
    if root_path in ("/", "/.", "/.."):
        _hold()
    cur = "/"
    for part in [p for p in root_path.split("/") if p]:
        if time.monotonic() >= deadline:
            raise _BudgetExpired()
        cur = cur + part if cur == "/" else f"{cur}/{part}"
        try:
            st = os.lstat(cur)
        except (KeyboardInterrupt, SystemExit, _BudgetExpired):
            raise
        except Exception:
            _hold()
        if stat.S_ISLNK(st.st_mode):
            _hold()
    if time.monotonic() >= deadline:
        raise _BudgetExpired()
    return root_path


def inspect_retained(
    root: str,
    expected_identity: tuple[int, int, int, int],
    trusted_context: dict[str, Any],
) -> dict[str, Any]:
    start_time = time.monotonic()
    deadline = start_time + _TIMEOUT_SECONDS

    def check_deadline() -> None:
        if time.monotonic() >= deadline:
            raise _BudgetExpired()

    report_state = {
        "prepared_journals": 0,
        "artifact_journals": 0,
        "verified_encrypted": 0,
        "prepared_intents": 0,
        "mutation_intents": 0,
        "completed_intents": 0,
        "unbound_snapshots": 0,
        "unbound_plain_restores": 0,
        "unbound_recovery": 0,
        "unbound_encrypted": 0,
        "other_files": 0,
        "entries": 0,
        "counted_bytes": 0,
        "record_bytes": 0,
        "hashed_bytes": 0,
    }

    try:
        try:
            if (
                type(expected_identity) is not tuple
                or len(expected_identity) != 4
                or any(type(x) is not int or isinstance(x, bool) for x in expected_identity)
            ):
                _hold()
            exp_dev, exp_ino, exp_uid, exp_mode = expected_identity
            if exp_dev < 1 or exp_ino < 1 or exp_uid < 0 or exp_mode != 0o700 or exp_uid != os.geteuid():
                _hold()

            ctx = _val_context(trusted_context)
            check_deadline()
            validated_root = _validate_root_path(root, deadline)
            check_deadline()
            intent_store = RestoreIntentStore(validated_root, ctx)
            check_deadline()
        except _BudgetExpired:
            raise
        except (KeyboardInterrupt, SystemExit, RuntimeError):
            raise
        except Exception:
            _hold()

        root_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            root_fd = os.open(validated_root, root_flags)
        except (KeyboardInterrupt, SystemExit, _BudgetExpired):
            raise
        except Exception:
            _hold()

        try:
            check_deadline()
            try:
                st_root = os.fstat(root_fd)
            except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                raise
            except Exception:
                _hold()

            if not stat.S_ISDIR(st_root.st_mode) or (st_root.st_mode & 0o7000) != 0 or stat.S_IMODE(st_root.st_mode) != 0o700:
                _hold()
            if st_root.st_uid != exp_uid or st_root.st_dev != exp_dev or st_root.st_ino != exp_ino:
                _hold()

            try:
                fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                raise
            except Exception:
                _hold()
            check_deadline()

            try:
                st_root_after = os.fstat(root_fd)
                st_named_root = os.lstat(validated_root)
            except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                raise
            except Exception:
                _hold()

            if (
                _stat_sig_blocks(st_root) != _stat_sig_blocks(st_root_after)
                or _stat_sig_blocks(st_root) != _stat_sig_blocks(st_named_root)
            ):
                _hold()
            check_deadline()

            total_entries = 0
            total_counted_bytes = max(st_root.st_size, st_root.st_blocks * 512)
            if total_counted_bytes > _MAX_ROOT_BYTES:
                _hold()
            report_state["counted_bytes"] = total_counted_bytes

            top_level_regular: list[str] = []
            nested_other_files = 0
            directory_metadata: dict[tuple[str, ...], tuple[int, ...]] = {(): _stat_sig_blocks(st_root)}
            recorded_entities: list[tuple[tuple[str, ...], tuple[int, ...]]] = []

            def scan(dir_fd: int, current_depth: int, parts: tuple[str, ...]) -> None:
                nonlocal total_entries, total_counted_bytes, nested_other_files
                check_deadline()
                if current_depth > _MAX_DEPTH:
                    _hold()

                try:
                    scanner = os.scandir(dir_fd)
                except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                    raise
                except Exception:
                    _hold()

                with scanner:
                    while True:
                        check_deadline()
                        try:
                            entry = next(scanner, None)
                        except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                            raise
                        except Exception:
                            _hold()
                        if entry is None:
                            break

                        total_entries += 1
                        if total_entries > _MAX_ENTRIES:
                            _hold()
                        report_state["entries"] = total_entries

                        name = entry.name
                        try:
                            st_named = os.lstat(name, dir_fd=dir_fd)
                        except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                            raise
                        except Exception:
                            _hold()

                        if stat.S_ISLNK(st_named.st_mode) or (st_named.st_mode & 0o7000) != 0:
                            _hold()
                        if st_named.st_dev != exp_dev or st_named.st_uid != exp_uid:
                            _hold()

                        mode = stat.S_IMODE(st_named.st_mode)
                        if (mode & 0o022) != 0:
                            _hold()

                        if stat.S_ISDIR(st_named.st_mode):
                            if mode not in (0o700, 0o755):
                                _hold()
                            sub_flags = (
                                os.O_RDONLY
                                | getattr(os, "O_DIRECTORY", 0)
                                | getattr(os, "O_NOFOLLOW", 0)
                                | getattr(os, "O_NONBLOCK", 0)
                                | getattr(os, "O_CLOEXEC", 0)
                            )
                            try:
                                sub_fd = os.open(name, sub_flags, dir_fd=dir_fd)
                            except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                                raise
                            except Exception:
                                _hold()
                            try:
                                st_sub = os.fstat(sub_fd)
                                if _stat_sig_blocks(st_sub) != _stat_sig_blocks(st_named):
                                    _hold()
                                allocated = max(st_sub.st_size, st_sub.st_blocks * 512)
                                total_counted_bytes += allocated
                                if total_counted_bytes > _MAX_ROOT_BYTES:
                                    _hold()
                                report_state["counted_bytes"] = total_counted_bytes
                                directory_metadata[parts + (name,)] = _stat_sig_blocks(st_sub)
                                recorded_entities.append((parts + (name,), _stat_sig_blocks(st_sub)))
                                scan(sub_fd, current_depth + 1, parts + (name,))
                                if _stat_sig_blocks(os.fstat(sub_fd)) != _stat_sig_blocks(st_sub):
                                    _hold()
                            finally:
                                try:
                                    os.close(sub_fd)
                                except Exception:
                                    pass
                        elif stat.S_ISREG(st_named.st_mode):
                            if mode not in (0o600, 0o644) or st_named.st_nlink != 1:
                                _hold()
                            reg_flags = (
                                os.O_RDONLY
                                | getattr(os, "O_NOFOLLOW", 0)
                                | getattr(os, "O_NONBLOCK", 0)
                                | getattr(os, "O_CLOEXEC", 0)
                            )
                            try:
                                file_fd = os.open(name, reg_flags, dir_fd=dir_fd)
                            except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                                raise
                            except Exception:
                                _hold()
                            try:
                                st_file = os.fstat(file_fd)
                                if _stat_sig_blocks(st_file) != _stat_sig_blocks(st_named):
                                    _hold()
                            finally:
                                try:
                                    os.close(file_fd)
                                except Exception:
                                    pass

                            try:
                                st_after = os.lstat(name, dir_fd=dir_fd)
                                if _stat_sig_blocks(st_after) != _stat_sig_blocks(st_named):
                                    _hold()
                            except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                                raise
                            except Exception:
                                _hold()

                            allocated = max(st_named.st_size, st_named.st_blocks * 512)
                            total_counted_bytes += allocated
                            if total_counted_bytes > _MAX_ROOT_BYTES:
                                _hold()
                            report_state["counted_bytes"] = total_counted_bytes
                            recorded_entities.append((parts + (name,), _stat_sig_blocks(st_named)))
                            if current_depth == 1:
                                top_level_regular.append(name)
                            else:
                                nested_other_files += 1
                        else:
                            _hold()

            scan(root_fd, 1, ())
            check_deadline()

            top_other_files = 0
            journal_records: list[tuple[str, dict[str, Any]]] = []
            all_referenced_leaves: set[str] = set()
            all_encrypted_leaves: set[str] = set()

            def read_record_file(leaf_name: str, expected_sig: tuple[int, ...]) -> bytes:
                check_deadline()
                try:
                    fd = os.open(leaf_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=root_fd)
                except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                    raise
                except Exception:
                    _hold()
                try:
                    st1 = os.fstat(fd)
                    if _stat_sig_blocks(st1) != expected_sig:
                        _hold()
                    if not stat.S_ISREG(st1.st_mode) or stat.S_IMODE(st1.st_mode) != 0o600 or st1.st_nlink != 1:
                        _hold()
                    if st1.st_uid != exp_uid or st1.st_dev != exp_dev or st1.st_size > _MAX_RECORD_FILE_SIZE:
                        _hold()
                    raw = b""
                    while True:
                        check_deadline()
                        chunk = os.read(fd, 2049)
                        if not chunk:
                            break
                        raw += chunk
                        if len(raw) > _MAX_RECORD_FILE_SIZE:
                            _hold()
                    if len(raw) != st1.st_size:
                        _hold()
                    report_state["record_bytes"] += len(raw)
                    if report_state["record_bytes"] > _MAX_RECORD_TOTAL_BYTES:
                        _hold()
                    st2 = os.fstat(fd)
                    named = os.lstat(leaf_name, dir_fd=root_fd)
                    if _stat_sig_blocks(st1) != _stat_sig_blocks(st2) or _stat_sig_blocks(named) != _stat_sig_blocks(st2):
                        _hold()
                    return raw
                finally:
                    try:
                        os.close(fd)
                    except Exception:
                        pass

            top_sig_map = {ent[0][0]: ent[1] for ent in recorded_entities if len(ent[0]) == 1}

            for name in sorted(top_level_regular):
                check_deadline()
                exp_sig = top_sig_map[name]
                if _JOURNAL_RE.match(name):
                    raw = read_record_file(name, exp_sig)
                    rec = _parse_and_validate_record(raw)
                    job_id = name[7:-5]
                    expected_digest = checkpoint_digest(ctx, job_id)
                    if rec["job_id"] != job_id or rec["request_digest"] != expected_digest:
                        _hold()
                    if rec["state"] == "prepared":
                        report_state["prepared_journals"] += 1
                    elif rec["state"] == "artifact-verified":
                        report_state["artifact_journals"] += 1
                        art = rec["artifact"]
                        if not isinstance(art, dict) or art.get("leaf") != f"sg-encrypted-{job_id}.bin":
                            _hold()
                        journal_records.append((name, rec))
                        all_referenced_leaves.add(art["leaf"])
                    else:
                        _hold()
                elif _INTENT_RE.match(name):
                    raw = read_record_file(name, exp_sig)
                    rec = intent_store._parse_and_validate_raw(raw, None)
                    job_id = name[11:-5]
                    payload = rec["payload"]
                    if payload["restore_job_id"] != job_id:
                        _hold()
                    st = rec["state"]
                    if st == "prepared":
                        report_state["prepared_intents"] += 1
                    elif st == "mutation-intent":
                        report_state["mutation_intents"] += 1
                    elif st == "completed-local":
                        report_state["completed_intents"] += 1
                    else:
                        _hold()
                elif _ENCRYPTED_RE.match(name):
                    all_encrypted_leaves.add(name)
                elif _SNAPSHOT_RE.match(name):
                    report_state["unbound_snapshots"] += 1
                elif _PLAIN_RE.match(name):
                    report_state["unbound_plain_restores"] += 1
                elif _RECOVERY_RE.match(name):
                    report_state["unbound_recovery"] += 1
                else:
                    top_other_files += 1

            report_state["other_files"] = top_other_files + nested_other_files
            report_state["unbound_encrypted"] = len(all_encrypted_leaves - all_referenced_leaves)

            hash_ops_count = 0
            for jname, rec in journal_records:
                check_deadline()
                art = rec["artifact"]
                leaf = art["leaf"]
                exp_size = art["bytes"]
                exp_sha = art["sha256"]

                if (
                    hash_ops_count + 1 > _MAX_HASH_OPERATIONS
                    or report_state["hashed_bytes"] + exp_size > _MAX_HASH_TOTAL_BYTES
                ):
                    raise _BudgetExpired()

                try:
                    fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=root_fd)
                except (KeyboardInterrupt, SystemExit, _BudgetExpired):
                    raise
                except Exception:
                    _hold()

                try:
                    st1 = os.fstat(fd)
                    if leaf in top_sig_map and _stat_sig_blocks(st1) != top_sig_map[leaf]:
                        _hold()
                    if not stat.S_ISREG(st1.st_mode) or stat.S_IMODE(st1.st_mode) != 0o600 or st1.st_nlink != 1:
                        _hold()
                    if st1.st_uid != exp_uid or st1.st_dev != exp_dev or st1.st_size != exp_size:
                        _hold()
                    hasher = hashlib.sha256()
                    h_bytes = 0
                    while True:
                        check_deadline()
                        chunk = os.read(fd, 65536)
                        if not chunk:
                            break
                        h_bytes += len(chunk)
                        report_state["hashed_bytes"] += len(chunk)
                        if h_bytes > exp_size:
                            _hold()
                        hasher.update(chunk)
                    if h_bytes != exp_size or hasher.hexdigest() != exp_sha:
                        _hold()
                    st2 = os.fstat(fd)
                    named = os.lstat(leaf, dir_fd=root_fd)
                    if _stat_sig_blocks(st1) != _stat_sig_blocks(st2) or _stat_sig_blocks(named) != _stat_sig_blocks(st2):
                        _hold()
                    hash_ops_count += 1
                    report_state["verified_encrypted"] += 1
                finally:
                    try:
                        os.close(fd)
                    except Exception:
                        pass

            check_deadline()

            for parts, observed in recorded_entities:
                check_deadline()
                parent = root_fd
                try:
                    for depth, component in enumerate(parts[:-1], 1):
                        check_deadline()
                        nxt = os.open(component, root_flags, dir_fd=parent)
                        if parent != root_fd:
                            os.close(parent)
                        parent = nxt
                        if _stat_sig_blocks(os.fstat(parent)) != directory_metadata[parts[:depth]]:
                            _hold()
                    check_deadline()
                    st_chk = os.lstat(parts[-1], dir_fd=parent)
                    if _stat_sig_blocks(st_chk) != observed:
                        _hold()
                finally:
                    if parent != root_fd:
                        try:
                            os.close(parent)
                        except Exception:
                            pass

            check_deadline()
            st_final_root_fd = os.fstat(root_fd)
            st_final_root_named = os.lstat(validated_root)
            if (
                _stat_sig_blocks(st_root) != _stat_sig_blocks(st_final_root_fd)
                or _stat_sig_blocks(st_root) != _stat_sig_blocks(st_final_root_named)
                or os.path.realpath(validated_root) != validated_root
            ):
                _hold()
            check_deadline()

            return {
                "schema": "sg.retained-report.v1",
                "complete": True,
                "reason": "complete",
                "external_writes_uncertain": 1,
                "prepared_journals": report_state["prepared_journals"],
                "artifact_journals": report_state["artifact_journals"],
                "verified_encrypted": report_state["verified_encrypted"],
                "prepared_intents": report_state["prepared_intents"],
                "mutation_intents": report_state["mutation_intents"],
                "completed_intents": report_state["completed_intents"],
                "unbound_snapshots": report_state["unbound_snapshots"],
                "unbound_plain_restores": report_state["unbound_plain_restores"],
                "unbound_recovery": report_state["unbound_recovery"],
                "unbound_encrypted": report_state["unbound_encrypted"],
                "other_files": report_state["other_files"],
                "entries": report_state["entries"],
                "counted_bytes": report_state["counted_bytes"],
                "record_bytes": report_state["record_bytes"],
                "hashed_bytes": report_state["hashed_bytes"],
            }
        finally:
            try:
                os.close(root_fd)
            except Exception:
                pass
    except _BudgetExpired:
        return {
            "schema": "sg.retained-report.v1",
            "complete": False,
            "reason": "budget_exhausted",
            "external_writes_uncertain": 1,
            "prepared_journals": report_state["prepared_journals"],
            "artifact_journals": report_state["artifact_journals"],
            "verified_encrypted": 0,
            "prepared_intents": report_state["prepared_intents"],
            "mutation_intents": report_state["mutation_intents"],
            "completed_intents": report_state["completed_intents"],
            "unbound_snapshots": report_state["unbound_snapshots"],
            "unbound_plain_restores": report_state["unbound_plain_restores"],
            "unbound_recovery": report_state["unbound_recovery"],
            "unbound_encrypted": report_state["unbound_encrypted"],
            "other_files": report_state["other_files"],
            "entries": report_state["entries"],
            "counted_bytes": report_state["counted_bytes"],
            "record_bytes": report_state["record_bytes"],
            "hashed_bytes": report_state["hashed_bytes"],
        }
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        _hold()

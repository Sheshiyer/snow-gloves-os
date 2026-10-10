"""Crash-safe, local-only bootstrap journal for Snow Gloves nodes.

This module deliberately grants no enrollment or readiness authority.  A
successful apply records local configuration only; held requirements remain
visible to callers and ``profile_ready`` is always false.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import re
import stat
import secrets
import sys
from typing import Any


SCHEMA = "snowgloves.node-plan.v1"
STATE_DIR = ".snowgloves-local"
MAX_PLAN_BYTES = 1_000_000
MAX_CONTENT_BYTES = 256_000
MAX_HELD = 256
MAX_HELD_ITEM = 4096
_HEX = re.compile(r"^[0-9a-f]{64}$")
_NODE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_STEP_SPEC = (
    ("identity", "node.json", ()),
    ("runtime", "runtime.json", ("identity",)),
    ("operations", "OPERATIONS.md", ("runtime",)),
)


class BootstrapError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _fail(message: str, code: int = 3) -> None:
    raise BootstrapError(message, code)


def _drift(message: str) -> None:
    _fail(message, 2)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        _fail(f"value is not canonical JSON: {exc}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_value(plan: dict[str, Any]) -> str:
    unsigned = {k: v for k, v in plan.items() if k != "digest"}
    return _sha(_canonical(unsigned))


def _validate_plan(plan: Any) -> dict[str, Any]:
    if type(plan) is not dict or set(plan) != {
        "schema", "node", "profile", "root", "source_digest", "steps", "held", "digest"
    }:
        _fail("plan must use the exact node-plan schema")
    if plan["schema"] != SCHEMA:
        _fail("unsupported plan schema")
    if type(plan["node"]) is not str or not _NODE.fullmatch(plan["node"]):
        _fail("invalid node slug")
    if plan["profile"] != "local-pilot":
        _fail("only local-pilot is supported")
    if type(plan["root"]) is not str or not os.path.isabs(plan["root"]):
        _fail("root must be an absolute path")
    if type(plan["source_digest"]) is not str or not _HEX.fullmatch(plan["source_digest"]):
        _fail("source_digest must be a SHA-256 digest")
    steps = plan["steps"]
    if type(steps) is not list or len(steps) != len(_STEP_SPEC):
        _fail("plan must contain the three required ordered steps")
    known: set[str] = set()
    for step, (want_id, want_path, want_deps) in zip(steps, _STEP_SPEC):
        if type(step) is not dict or set(step) != {"id", "path", "content", "depends_on"}:
            _fail("step must use the exact step schema")
        if step["id"] != want_id or step["path"] != want_path:
            _fail("step order or path is invalid")
        if type(step["content"]) is not str:
            _fail("step content must be a UTF-8 string")
        try:
            raw = step["content"].encode("utf-8", "strict")
        except UnicodeError:
            _fail("step content is not valid UTF-8")
        if len(raw) > MAX_CONTENT_BYTES or "\x00" in step["content"]:
            _fail("step content exceeds its bound or contains NUL")
        if type(step["depends_on"]) is not list or step["depends_on"] != list(want_deps):
            _fail("step dependencies are invalid")
        if any(dep not in known for dep in step["depends_on"]):
            _fail("step dependencies must refer to earlier steps")
        known.add(step["id"])
    held = plan["held"]
    if type(held) is not list or len(held) > MAX_HELD:
        _fail("held must be a bounded list")
    for item in held:
        if type(item) is not str or not item:
            _fail("held entries must be non-empty bounded strings")
        try:
            held_size = len(item.encode("utf-8", "strict"))
        except UnicodeError:
            _fail("held entries must be valid UTF-8 strings")
        if held_size > MAX_HELD_ITEM:
            _fail("held entries must be non-empty bounded strings")
    digest = plan["digest"]
    if type(digest) is not str or not _HEX.fullmatch(digest) or digest != _digest_value(plan):
        _fail("plan digest does not match canonical plan contents")
    encoded = _canonical(plan)
    if len(encoded) > MAX_PLAN_BYTES:
        _fail("plan exceeds size limit")
    return plan


def digest_plan(plan: dict[str, Any]) -> str:
    """Validate and return the digest for a plan (ignoring its digest field).

    For caller convenience, the digest may be absent or blank while preparing
    a plan; all other closed-schema checks still apply.
    """
    if type(plan) is not dict:
        _fail("plan must be an object")
    candidate = dict(plan)
    candidate["digest"] = "0" * 64
    # Compute against the caller's unsigned contents, then validate with that digest.
    digest = _digest_value(candidate)
    candidate["digest"] = digest
    _validate_plan(candidate)
    return digest


def _open_dir(path: str) -> int:
    """Open an absolute directory by components, refusing symlinks."""
    if not os.path.isabs(path):
        _fail("directory path must be absolute")
    parts = [p for p in path.split(os.sep) if p]
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts:
            if part in (".", ".."):
                _fail("dot components are forbidden")
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _root_fd(root: str) -> int:
    try:
        fd = _open_dir(root)
        canonical = os.path.realpath(root)
        if canonical != os.path.normpath(root):
            os.close(fd)
            _fail("root path is not canonical")
        return fd
    except (OSError, ValueError) as exc:
        _fail(f"cannot safely open root: {exc}")


def _mkdir_open(parent: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
        os.fsync(parent)
    except FileExistsError:
        pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)


def _state_fd(rootfd: int, create: bool) -> int:
    try:
        if create:
            return _mkdir_open(rootfd, STATE_DIR)
        return os.open(STATE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=rootfd)
    except OSError as exc:
        _fail(f"cannot safely open journal state: {exc}")


def _lock(statefd: int) -> int:
    try:
        fd = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=statefd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            os.close(fd)
            _fail("journal lock is not a private regular file", 2)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            _fail("another bootstrap operation holds the journal lock", 2)
        return fd
    except OSError as exc:
        _fail(f"cannot acquire journal lock: {exc}", 2)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def _no_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _read_json_at(dirfd: int, name: str) -> dict[str, Any] | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=dirfd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        _fail(f"cannot safely open {name}: {exc}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_PLAN_BYTES:
            _fail(f"{name} is not a bounded private regular file")
        raw = b""
        while len(raw) <= MAX_PLAN_BYTES:
            chunk = os.read(fd, min(65536, MAX_PLAN_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        if len(raw) > MAX_PLAN_BYTES:
            _fail(f"{name} exceeds size limit")
        try:
            val = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_no_constant)
        except (UnicodeError, ValueError, RecursionError) as exc:
            _fail(f"{name} is invalid JSON: {exc}")
        if type(val) is not dict:
            _fail(f"{name} must contain an object")
        return val
    finally:
        os.close(fd)


def _atomic_json(statefd: int, value: dict[str, Any]) -> None:
    raw = _canonical(value)
    name = ".journal-" + secrets.token_hex(12)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=statefd)
    except OSError as exc:
        _fail(f"cannot create private journal temporary: {exc}")
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fsync(fd)
        st = os.fstat(fd)
        # Rename within the already-open state directory, then verify identity.
        os.replace(name, "journal.json", src_dir_fd=statefd, dst_dir_fd=statefd)
        now = os.stat("journal.json", dir_fd=statefd, follow_symlinks=False)
        if (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
            _fail("journal changed during publication")
        os.fsync(statefd)
    except OSError as exc:
        _fail(f"cannot persist journal: {exc}")
    finally:
        os.close(fd)
        try:
            os.unlink(name, dir_fd=statefd)
        except OSError:
            pass


def _step_parent(rootfd: int, rel: str, create: bool) -> tuple[int, str]:
    pieces = rel.split("/")
    if any(p in ("", ".", "..") or "/" in p for p in pieces):
        _fail("unsafe step path")
    fd = os.dup(rootfd)
    try:
        for part in pieces[:-1]:
            if create:
                nxt = _mkdir_open(fd, part)
            else:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd, pieces[-1]
    except OSError as exc:
        os.close(fd)
        _fail(f"cannot safely open target directory: {exc}")


def _read_target(parent: int, name: str) -> tuple[bytes, os.stat_result] | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        return None
    except OSError as exc:
        _fail(f"target {name} is not a safe regular file: {exc}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink < 1:
            _fail(f"target {name} is not a regular file")
        data = b""
        while len(data) <= MAX_CONTENT_BYTES:
            chunk = os.read(fd, min(65536, MAX_CONTENT_BYTES + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        if len(data) > MAX_CONTENT_BYTES:
            _fail(f"target {name} exceeds size limit")
        now = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (st.st_dev, st.st_ino) != (now.st_dev, now.st_ino):
            _fail(f"target {name} changed while being read")
        return data, st
    finally:
        os.close(fd)


def _journal_validate(j: Any, plan: dict[str, Any], digest: str) -> dict[str, Any]:
    _validate_status_journal(j, plan["root"])
    keys = {"schema", "plan_digest", "source_digest", "node", "root", "state", "steps", "held"}
    if type(j) is not dict or set(j) != keys:
        _fail("journal has an invalid closed schema")
    if (j["schema"] != "snowgloves.node-journal.v1" or j["plan_digest"] != digest or
            j["source_digest"] != plan["source_digest"] or j["node"] != plan["node"] or j["root"] != plan["root"]):
        _fail("journal does not bind to this plan and source")
    if j["state"] not in ("applying", "configured", "rolling-back", "rolled-back", "manual-recovery"):
        _fail("journal state is invalid")
    if j["held"] != plan["held"] or type(j["steps"]) is not list or len(j["steps"]) != 3:
        _fail("journal step set is invalid")
    for rec, (spec, pstep) in zip(j["steps"], zip(_STEP_SPEC, plan["steps"])):
        want_id, want_path, _ = spec
        if type(rec) is not dict or set(rec) != {"id", "path", "status", "sha256", "size", "owned", "dev", "ino"}:
            _fail("journal receipt has an invalid schema")
        if rec["id"] != want_id or rec["path"] != want_path or rec["sha256"] != _sha(pstep["content"].encode("utf-8")):
            _fail("journal receipt path or content binding is invalid")
        if rec["status"] not in ("pending", "complete", "removing", "rolled-back") or type(rec["owned"]) is not bool:
            _fail("journal receipt status is invalid")
        if type(rec["size"]) is not int or rec["size"] != len(pstep["content"].encode("utf-8")):
            _fail("journal receipt size is invalid")
        if rec["status"] in ("complete", "removing") and (type(rec["dev"]) is not int or type(rec["ino"]) is not int):
            _fail("complete receipt lacks file identity")
        if rec["status"] not in ("complete", "removing") and (rec["dev"] is not None or rec["ino"] is not None):
            _fail("incomplete receipt cannot claim file identity")
    return j


def _fresh_journal(plan: dict[str, Any], digest: str) -> dict[str, Any]:
    return {"schema": "snowgloves.node-journal.v1", "plan_digest": digest,
            "source_digest": plan["source_digest"], "node": plan["node"], "root": plan["root"],
            "state": "applying", "held": plan["held"],
            "steps": [{"id": sid, "path": path, "status": "pending",
                       "sha256": _sha(plan["steps"][i]["content"].encode("utf-8")),
                       "size": len(plan["steps"][i]["content"].encode("utf-8")),
                       "owned": False, "dev": None, "ino": None}
                      for i, (sid, path, _) in enumerate(_STEP_SPEC)]}


def _anchor_dir(statefd: int, create: bool) -> int:
    try:
        return _mkdir_open(statefd, "anchors") if create else os.open(
            "anchors", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=statefd)
    except OSError as exc:
        _fail(f"cannot safely open ownership anchors: {exc}")


def _anchor_name(index: int) -> str:
    return f"{index}.anchor"


def _ensure_anchor(afd: int, idx: int, content: bytes) -> os.stat_result:
    name = _anchor_name(idx)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=afd)
    except FileNotFoundError:
        fd = -1
    except OSError as exc:
        _fail(f"ownership anchor is unsafe: {exc}")
    if fd >= 0:
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                _fail("ownership anchor is not a regular file")
            data = os.read(fd, MAX_CONTENT_BYTES + 1)
            if data != content:
                _fail("ownership anchor does not match expected content")
            return st
        finally:
            os.close(fd)
    tmp = f".{idx}-{secrets.token_hex(12)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=afd)
    try:
        view = memoryview(content)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fsync(fd)
        st = os.fstat(fd)
        try:
            os.link(tmp, name, src_dir_fd=afd, dst_dir_fd=afd, follow_symlinks=False)
        except FileExistsError:
            os.close(fd)
            fd = -1
            return _ensure_anchor(afd, idx, content)
        os.fsync(afd)
        os.unlink(tmp, dir_fd=afd)
        os.fsync(afd)
        return os.stat(name, dir_fd=afd, follow_symlinks=False)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp, dir_fd=afd)
        except OSError:
            pass


def _existing_anchor(afd: int, idx: int, content: bytes) -> os.stat_result | None:
    try:
        fd = os.open(_anchor_name(idx), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=afd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        _fail(f"ownership anchor is unsafe: {exc}")
    try:
        st = os.fstat(fd)
        data = b""
        while len(data) <= MAX_CONTENT_BYTES:
            chunk = os.read(fd, min(65536, MAX_CONTENT_BYTES + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        if not stat.S_ISREG(st.st_mode):
            _fail("ownership anchor is not a regular file")
        if data != content:
            _fail("ownership anchor does not match expected content")
        return st
    finally:
        os.close(fd)


def _link_noclobber(srcfd: int, src: str, dstfd: int, dst: str) -> bool:
    try:
        os.link(src, dst, src_dir_fd=srcfd, dst_dir_fd=dstfd, follow_symlinks=False)
        os.fsync(dstfd)
        return True
    except FileExistsError:
        return False
    except OSError as exc:
        _fail(f"cannot publish target without clobbering: {exc}")


def _rename_noreplace(srcfd: int, src: str, dstfd: int, dst: str) -> None:
    """Atomically capture a target without replacing existing recovery data."""
    libc = ctypes.CDLL(None, use_errno=True)
    src_b, dst_b = os.fsencode(src), os.fsencode(dst)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        fn = libc.renameat2
        fn.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        fn.restype = ctypes.c_int
        result = fn(srcfd, src_b, dstfd, dst_b, 1)  # RENAME_NOREPLACE
    elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        fn = libc.renameatx_np
        fn.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        fn.restype = ctypes.c_int
        result = fn(srcfd, src_b, dstfd, dst_b, 4)  # RENAME_EXCL
    else:
        _drift("platform lacks atomic exclusive rollback capture; manual recovery required")
    if result != 0:
        err = ctypes.get_errno()
        _drift(f"atomic rollback capture failed; manual recovery required: {os.strerror(err)}")


def _apply_one(rootfd: int, statefd: int, afd: int, plan: dict[str, Any], j: dict[str, Any], idx: int) -> None:
    rec = j["steps"][idx]
    step = plan["steps"][idx]
    content = step["content"].encode("utf-8")
    if rec["status"] == "pending":
        _atomic_json(statefd, j)
    parent, name = _step_parent(rootfd, step["path"], True)
    try:
        present = _read_target(parent, name)
        if rec["status"] == "complete":
            if present is None or present[0] != content or (present[1].st_dev, present[1].st_ino) != (rec["dev"], rec["ino"]):
                _drift(f"completed target drifted: {step['path']}")
            if rec["owned"]:
                anchor = _existing_anchor(afd, idx, content)
                if anchor is None:
                    _drift(f"installer ownership proof is missing: {step['path']}")
                if (anchor.st_dev, anchor.st_ino) != (present[1].st_dev, present[1].st_ino):
                    _drift(f"installer ownership proof failed: {step['path']}")
            else:
                anchor = _existing_anchor(afd, idx, content)
                if anchor and (anchor.st_dev, anchor.st_ino) == (present[1].st_dev, present[1].st_ino):
                    _drift(f"journal ownership claim was altered: {step['path']}")
            return
        if present is not None:
            if present[0] != content:
                _drift(f"refusing to clobber foreign target: {step['path']}")
            # A matching anchor proves this exact inode came from our interrupted
            # publication. Identical foreign bytes have a different inode.
            anchor = _existing_anchor(afd, idx, content)
            owned = bool(anchor and (anchor.st_dev, anchor.st_ino) ==
                         (present[1].st_dev, present[1].st_ino))
            rec.update(status="complete", owned=owned, dev=present[1].st_dev, ino=present[1].st_ino)
            _atomic_json(statefd, j)
            return
        anchor = _ensure_anchor(afd, idx, content)
        if not _link_noclobber(afd, _anchor_name(idx), parent, name):
            raced = _read_target(parent, name)
            if raced is None or raced[0] != content:
                _drift(f"target appeared with different content: {step['path']}")
            rec.update(status="complete", owned=False, dev=raced[1].st_dev, ino=raced[1].st_ino)
            _atomic_json(statefd, j)
            return
        now = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (now.st_dev, now.st_ino) != (anchor.st_dev, anchor.st_ino):
            _drift(f"target identity changed during publication: {step['path']}")
        rec.update(status="complete", owned=True, dev=now.st_dev, ino=now.st_ino)
        _atomic_json(statefd, j)
    finally:
        os.close(parent)


def _result(j: dict[str, Any]) -> dict[str, Any]:
    return {"state": j["state"], "node": j["node"], "profile": "local-pilot",
            "plan_digest": j["plan_digest"], "source_digest": j["source_digest"],
            "held": list(j["held"]), "profile_ready": False,
            "steps": [{k: rec[k] for k in ("id", "path", "status", "owned", "sha256", "size")}
                      for rec in j["steps"]]}


def _validate_status_journal(j: Any, root: str) -> dict[str, Any]:
    keys = {"schema", "plan_digest", "source_digest", "node", "root", "state", "steps", "held"}
    if type(j) is not dict or set(j) != keys:
        _fail("journal has an invalid closed schema")
    if (j["schema"] != "snowgloves.node-journal.v1" or type(j["plan_digest"]) is not str or
            not _HEX.fullmatch(j["plan_digest"]) or type(j["source_digest"]) is not str or
            not _HEX.fullmatch(j["source_digest"]) or type(j["node"]) is not str or
            not _NODE.fullmatch(j["node"]) or type(j["root"]) is not str or j["root"] != root):
        _fail("journal binding fields are invalid")
    if j["state"] not in ("applying", "configured", "rolling-back", "rolled-back", "manual-recovery"):
        _fail("journal state is invalid")
    if type(j["held"]) is not list or len(j["held"]) > MAX_HELD:
        _fail("journal held requirements are invalid")
    for item in j["held"]:
        if type(item) is not str or not item:
            _fail("journal held requirement has the wrong type")
        try:
            size = len(item.encode("utf-8", "strict"))
        except UnicodeError:
            _fail("journal held requirement is invalid UTF-8")
        if size > MAX_HELD_ITEM:
            _fail("journal held requirement exceeds size limit")
    if type(j["steps"]) is not list or len(j["steps"]) != len(_STEP_SPEC):
        _fail("journal steps are invalid")
    for i, rec in enumerate(j["steps"]):
        if type(rec) is not dict or set(rec) != {"id", "path", "status", "sha256", "size", "owned", "dev", "ino"}:
            _fail("journal receipt schema is invalid")
        if rec["id"] != _STEP_SPEC[i][0] or rec["path"] != _STEP_SPEC[i][1]:
            _fail("journal path binding is invalid")
        if type(rec["status"]) is not str or rec["status"] not in ("pending", "complete", "removing", "rolled-back"):
            _fail("journal receipt status is invalid")
        if type(rec["sha256"]) is not str or not _HEX.fullmatch(rec["sha256"]):
            _fail("journal receipt digest is invalid")
        if type(rec["size"]) is not int or not 0 <= rec["size"] <= MAX_CONTENT_BYTES:
            _fail("journal receipt size is invalid")
        if type(rec["owned"]) is not bool:
            _fail("journal ownership flag is invalid")
        if rec["status"] in ("complete", "removing"):
            if type(rec["dev"]) is not int or type(rec["ino"]) is not int or rec["dev"] < 0 or rec["ino"] <= 0:
                _fail("complete receipt lacks valid file identity")
        elif rec["dev"] is not None or rec["ino"] is not None or (rec["status"] == "pending" and rec["owned"]):
            _fail("incomplete receipt has invalid ownership claims")
    return j


def apply(plan: dict[str, Any], reviewed_digest: str, *, resume: bool = False) -> dict[str, Any]:
    plan = _validate_plan(plan)
    if type(reviewed_digest) is not str or reviewed_digest != plan["digest"]:
        _fail("reviewed digest does not match plan")
    rootfd = _root_fd(plan["root"])
    try:
        statefd = _state_fd(rootfd, True)
        try:
            lockfd = _lock(statefd)
            try:
                existing = _read_json_at(statefd, "journal.json")
                if existing is None:
                    j = _fresh_journal(plan, reviewed_digest)
                    _atomic_json(statefd, j)
                else:
                    j = _journal_validate(existing, plan, reviewed_digest)
                    if j["state"] == "configured":
                        # Recheck all targets before reporting idempotent success.
                        afd = _anchor_dir(statefd, False)
                        try:
                            for idx in range(3):
                                _apply_one(statefd, statefd, afd, plan, j, idx)
                        finally:
                            os.close(afd)
                        return _result(j)
                    if j["state"] in ("rolling-back", "manual-recovery"):
                        _fail("journal is in rollback or recovery; apply is not safe")
                    if j["state"] == "rolled-back":
                        _fail("journal was rolled back; use a new reviewed plan")
                    if not resume:
                        _fail("journal exists; explicit resume is required")
                afd = _anchor_dir(statefd, True)
                try:
                    for idx in range(3):
                        _apply_one(statefd, statefd, afd, plan, j, idx)
                    j["state"] = "configured"
                    _atomic_json(statefd, j)
                    return _result(j)
                finally:
                    os.close(afd)
            finally:
                os.close(lockfd)
        finally:
            os.close(statefd)
    finally:
        os.close(rootfd)


def _rollback_locked(rootfd: int, statefd: int, afd: int, plan: dict[str, Any], j: dict[str, Any]) -> dict[str, Any]:
    j["state"] = "rolling-back"
    _atomic_json(statefd, j)
    for idx in reversed(range(3)):
        rec = j["steps"][idx]
        if rec["status"] == "rolled-back":
            continue
        parent, name = _step_parent(statefd, rec["path"], False)
        try:
            present = _read_target(parent, name)
            content = plan["steps"][idx]["content"].encode("utf-8")
            qfd = _mkdir_open(statefd, "quarantine")
            qname = f"{idx}.capture"
            try:
                captured = _read_target(qfd, qname)
                if captured is not None:
                    anchor = _existing_anchor(afd, idx, content)
                    expected = (rec["dev"], rec["ino"]) if rec["dev"] is not None else (
                        anchor.st_dev, anchor.st_ino) if anchor else (None, None)
                    if (anchor is None or captured[0] != content or
                            (captured[1].st_dev, captured[1].st_ino) != expected or
                            (anchor.st_dev, anchor.st_ino) != expected):
                        _drift(f"untrusted rollback capture requires manual recovery: {rec['path']}")
                    rec.update(status="removing", owned=True,
                               dev=captured[1].st_dev, ino=captured[1].st_ino)
                    _atomic_json(statefd, j)
                    os.unlink(qname, dir_fd=qfd)
                    os.fsync(qfd)
                    rec.update(status="rolled-back", dev=None, ino=None)
                    _atomic_json(statefd, j)
                    continue
            finally:
                os.close(qfd)
            if present is None:
                if rec["status"] == "removing":
                    rec.update(status="rolled-back", dev=None, ino=None)
                    _atomic_json(statefd, j)
                    continue
                if rec["owned"]:
                    anchor = _existing_anchor(afd, idx, plan["steps"][idx]["content"].encode("utf-8"))
                    if anchor is None:
                        _drift("missing owned target has no ownership proof")
                    _drift(f"owned target disappeared before rollback: {rec['path']}")
                rec.update(status="rolled-back", dev=None, ino=None)
                _atomic_json(statefd, j)
                continue
            if present[0] != content:
                _drift(f"target drift prevents rollback: {rec['path']}")
            anchor = _existing_anchor(afd, idx, content)
            anchor_proves = bool(anchor and (anchor.st_dev, anchor.st_ino) ==
                                 (present[1].st_dev, present[1].st_ino))
            if rec["status"] == "pending" and not rec["owned"] and anchor_proves:
                # Recover a commit interrupted after link publication.
                pass
            elif not rec["owned"]:
                if anchor_proves and rec["status"] == "complete":
                    _drift(f"ownership receipt was altered: {rec['path']}")
                rec.update(status="rolled-back", dev=None, ino=None)
                _atomic_json(statefd, j)
                continue
            elif (not anchor_proves or (present[1].st_dev, present[1].st_ino) != (rec["dev"], rec["ino"])):
                _drift(f"ownership proof prevents rollback: {rec['path']}")
            # Rename into private quarantine, then verify the captured inode
            # before unlinking so a last-moment replacement is never deleted.
            qfd = _mkdir_open(statefd, "quarantine")
            try:
                if _read_target(qfd, qname) is not None:
                    _drift(f"rollback capture path is already occupied: {rec['path']}")
                _rename_noreplace(parent, name, qfd, qname)
                os.fsync(parent)
                os.fsync(qfd)
                captured = _read_target(qfd, qname)
                if (captured is None or captured[0] != content or
                        (captured[1].st_dev, captured[1].st_ino) != (anchor.st_dev, anchor.st_ino)):
                    _drift(f"target changed during rollback capture: {rec['path']}")
                rec.update(status="removing", owned=True,
                           dev=captured[1].st_dev, ino=captured[1].st_ino)
                _atomic_json(statefd, j)
                os.unlink(qname, dir_fd=qfd)
                os.fsync(qfd)
            finally:
                os.close(qfd)
            rec.update(status="rolled-back", dev=None, ino=None)
            _atomic_json(statefd, j)
        except BootstrapError:
            j["state"] = "manual-recovery"
            _atomic_json(statefd, j)
            raise
        finally:
            os.close(parent)
    j["state"] = "rolled-back"
    _atomic_json(statefd, j)
    return _result(j)


def rollback(plan: dict[str, Any], reviewed_digest: str) -> dict[str, Any]:
    plan = _validate_plan(plan)
    if type(reviewed_digest) is not str or reviewed_digest != plan["digest"]:
        _fail("reviewed digest does not match plan")
    rootfd = _root_fd(plan["root"])
    try:
        statefd = _state_fd(rootfd, False)
        try:
            lockfd = _lock(statefd)
            try:
                j = _journal_validate(_read_json_at(statefd, "journal.json"), plan, reviewed_digest)
                if j["state"] == "rolled-back":
                    return _result(j)
                afd = _anchor_dir(statefd, True)
                try:
                    return _rollback_locked(rootfd, statefd, afd, plan, j)
                finally:
                    os.close(afd)
            finally:
                os.close(lockfd)
        finally:
            os.close(statefd)
    finally:
        os.close(rootfd)


def status(root: str) -> dict[str, Any]:
    """Read-only local journal status; never creates state or a lock file."""
    if type(root) is not str or not os.path.isabs(root):
        _fail("root must be an absolute path")
    rootfd = _root_fd(root)
    try:
        try:
            statefd = _state_fd(rootfd, False)
        except BootstrapError as exc:
            if "No such file" in str(exc):
                return {"state": "absent", "profile_ready": False}
            raise
        try:
            j = _read_json_at(statefd, "journal.json")
            if j is None:
                return {"state": "absent", "profile_ready": False}
            # No caller plan is needed to inspect a journal, but enforce a strict
            # shape and known fixed step paths before exposing its claims.
            j = _validate_status_journal(j, root)
            return _result(j)
        finally:
            os.close(statefd)
    finally:
        os.close(rootfd)

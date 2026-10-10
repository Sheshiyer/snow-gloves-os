#!/usr/bin/env python3
"""Read-only inspection and local-only node bootstrap CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Any

# CLI commands must not leave bytecode artifacts in the source or install tree.
sys.dont_write_bytecode = True
import node_journal as journal


SCHEMA = "snowgloves.node-plan.v1"
NODE_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
MAX_PLAN_BYTES = 1_000_000
HELD = [
    "live identity enrollment is unverified",
    "vault readiness is unverified",
    "services readiness is unverified",
    "network readiness is unverified",
    "provider readiness is unverified",
    "physical acceptance is unverified",
]
TOOLS = ("codex", "claude", "node", "npm", "bun", "uv", "gh", "git", "python3", "opencode", "ollama")


class UsageError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_root(root: str | os.PathLike[str]) -> str:
    raw = os.fspath(root)
    if not os.path.isabs(raw):
        journal._fail("root must be an absolute path")
    # This opens every component with O_NOFOLLOW and verifies an existing directory.
    fd = journal._root_fd(raw)
    os.close(fd)
    normalized = os.path.normpath(raw)
    if normalized != raw:
        journal._fail("root must be absolute and normalized")
    return raw


def source_digest() -> str:
    """Hash exact source bytes with labels and explicit length framing."""
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    rootfd = journal._open_dir(base)
    try:
        scriptsfd = os.open("scripts", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=rootfd)
        try:
            files = (("VERSION", rootfd, "VERSION"),
                     ("scripts/node_bootstrap.py", scriptsfd, "node_bootstrap.py"),
                     ("scripts/node_journal.py", scriptsfd, "node_journal.py"))
            loaded = [(label, _read_source_at(parentfd, name)) for label, parentfd, name in files]
        finally:
            os.close(scriptsfd)
    finally:
        os.close(rootfd)
    h = hashlib.sha256()
    for label, data in loaded:
        name = label.encode("utf-8")
        h.update(len(name).to_bytes(4, "big"))
        h.update(name)
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def _read_source_at(parentfd: int, name: str) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     dir_fd=parentfd)
    except OSError as exc:
        journal._fail(f"cannot safely open a local source file: {exc}")
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_PLAN_BYTES * 8:
            journal._fail("local source file is not a bounded regular file")
        data = bytearray()
        while len(data) <= MAX_PLAN_BYTES * 8:
            chunk = os.read(fd, min(65536, MAX_PLAN_BYTES * 8 + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=parentfd, follow_symlinks=False)
        if (len(data) > MAX_PLAN_BYTES * 8 or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)):
            journal._fail("local source file changed while being read")
        return bytes(data)
    finally:
        os.close(fd)


def _ram_bytes() -> int | None:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        value = int(page_size) * int(pages)
        return value if value > 0 else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def inspect(root: str | os.PathLike[str]) -> dict[str, Any]:
    root_path = _canonical_root(root)
    try:
        disk = shutil.disk_usage(root_path)
        disk_info: dict[str, int | None] = {"total_bytes": disk.total, "used_bytes": disk.used,
                                            "free_bytes": disk.free}
    except OSError:
        disk_info = {"total_bytes": None, "used_bytes": None, "free_bytes": None}
    tools: dict[str, dict[str, Any]] = {}
    for name in TOOLS:
        path = shutil.which(name)
        tools[name] = {"present": path is not None, "path": path}
    return {
        "root": root_path,
        "platform": {"system": platform.system() or "unknown", "release": platform.release() or "unknown"},
        "machine": platform.machine() or "unknown",
        "ram_bytes": _ram_bytes(),
        "disk": disk_info,
        "tools": tools,
    }


def make_plan(root: str | os.PathLike[str], node: str) -> dict[str, Any]:
    root_path = _canonical_root(root)
    if type(node) is not str or not NODE_RE.fullmatch(node):
        journal._fail("node slug is invalid")
    identity = {"node": node, "profile": "local-pilot", "schema": "snowgloves.node-identity.v1"}
    runtime = {"profile": "local-pilot", "runtime": "local", "schema": "snowgloves.node-runtime.v1"}
    operations = (
        "# Local node operations\n\n"
        f"Node: `{node}`\n\n"
        "This file records local bootstrap configuration only. Identity, vault, "
        "services, network, providers, and physical acceptance remain held for "
        "independent verification.\n"
    )
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "node": node,
        "profile": "local-pilot",
        "root": root_path,
        "source_digest": source_digest(),
        "steps": [
            {"id": "identity", "path": "node.json", "content": _json_bytes(identity).decode("utf-8") + "\n",
             "depends_on": []},
            {"id": "runtime", "path": "runtime.json", "content": _json_bytes(runtime).decode("utf-8") + "\n",
             "depends_on": ["identity"]},
            {"id": "operations", "path": "OPERATIONS.md", "content": operations,
             "depends_on": ["runtime"]},
        ],
        "held": list(HELD),
    }
    plan["digest"] = journal.digest_plan(plan)
    return plan


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(_: str) -> None:
    raise ValueError("non-finite number")


def _read_plan(path: str) -> dict[str, Any]:
    absolute = os.path.abspath(path)
    parent_path, name = os.path.split(absolute)
    if not name or name in (".", ".."):
        journal._fail("plan path is invalid")
    try:
        parentfd = journal._open_dir(parent_path)
    except OSError as exc:
        journal._fail(f"cannot safely open plan directory: {exc}")
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=parentfd)
        except OSError as exc:
            journal._fail(f"cannot safely open plan: {exc}")
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_PLAN_BYTES:
                journal._fail("plan must be a bounded regular file")
            raw = bytearray()
            while len(raw) <= MAX_PLAN_BYTES:
                chunk = os.read(fd, min(65536, MAX_PLAN_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            after = os.fstat(fd)
            current = os.stat(name, dir_fd=parentfd, follow_symlinks=False)
            if (len(raw) > MAX_PLAN_BYTES or
                    (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) !=
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                    (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)):
                journal._fail("plan changed while being read")
        finally:
            os.close(fd)
    finally:
        os.close(parentfd)
    try:
        value = json.loads(bytes(raw).decode("utf-8", "strict"), object_pairs_hook=_pairs,
                          parse_constant=_no_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        journal._fail(f"plan JSON is invalid: {exc}")
    if type(value) is not dict:
        journal._fail("plan must be a JSON object")
    journal._validate_plan(value)
    return value


def _read_local_file(root: str, name: str, max_bytes: int = journal.MAX_CONTENT_BYTES) -> bytes | None:
    try:
        rfd = journal._root_fd(root)
    except journal.BootstrapError:
        return None
    try:
        try:
            sfd = os.open(journal.STATE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                          dir_fd=rfd)
        except OSError:
            return None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=sfd)
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
                    return None
                out = bytearray()
                while len(out) <= max_bytes:
                    chunk = os.read(fd, min(65536, max_bytes + 1 - len(out)))
                    if not chunk:
                        break
                    out.extend(chunk)
                after = os.fstat(fd)
                current = os.stat(name, dir_fd=sfd, follow_symlinks=False)
                if ((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) !=
                        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                        (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)):
                    return None
                return bytes(out) if len(out) <= max_bytes else None
            finally:
                os.close(fd)
        except OSError:
            return None
        finally:
            os.close(sfd)
    finally:
        os.close(rfd)


def _finding(check_id: str, status: str, reason: str, remediation: str, evidence: Any) -> dict[str, Any]:
    return {"id": check_id, "status": status, "reason": reason,
            "observed_at": int(time.time()), "evidence_digest": _sha(_json_bytes(evidence)),
            "remediation": remediation}


def _doctor_data(root: str) -> tuple[dict[str, Any], int]:
    root_path = _canonical_root(root)
    observed = inspect(root_path)
    try:
        journal_status = journal.status(root_path)
    except journal.BootstrapError:
        journal_status = {"state": "invalid", "profile_ready": False, "steps": []}
    node_name = None
    identity_raw = _read_local_file(root_path, "node.json")
    if identity_raw is not None:
        try:
            ident = json.loads(identity_raw.decode("utf-8", "strict"), object_pairs_hook=_pairs,
                               parse_constant=_no_constant)
            if type(ident) is dict and ident.get("schema") == "snowgloves.node-identity.v1" and type(ident.get("node")) is str and NODE_RE.fullmatch(ident["node"]):
                node_name = ident["node"]
        except (UnicodeError, ValueError, RecursionError):
            node_name = None
    findings: list[dict[str, Any]] = []
    local_ok = node_name is not None
    if local_ok:
        expected = make_plan(root_path, node_name)
        for idx, step in enumerate(expected["steps"]):
            actual = _read_local_file(root_path, step["path"])
            expected_bytes = step["content"].encode("utf-8")
            receipt = journal_status.get("steps", [])[idx] if len(journal_status.get("steps", [])) == 3 else {}
            valid = (actual == expected_bytes and journal_status.get("state") == "configured" and
                     journal_status.get("plan_digest") == expected["digest"] and
                     journal_status.get("source_digest") == expected["source_digest"] and
                     journal_status.get("held") == expected["held"] and
                     receipt.get("status") == "complete" and receipt.get("sha256") == _sha(expected_bytes) and
                     receipt.get("size") == len(expected_bytes))
            findings.append(_finding(
                f"local-{step['id']}", "pass" if valid else "fail",
                "local file and journal receipt verified" if valid else "local file or journal receipt is absent or invalid",
                "review the plan and apply it again after resolving local drift",
                {"present": actual is not None, "actual_digest": _sha(actual) if actual is not None else None,
                 "expected_digest": _sha(expected_bytes), "journal_state": journal_status.get("state"),
                 "receipt_status": receipt.get("status")},
            ))
            local_ok = local_ok and valid
    else:
        findings.append(_finding("local-identity", "fail", "local identity file is absent or invalid",
                                 "create and review a local-pilot node plan", {"present": identity_raw is not None}))
    for idx, reason in enumerate(HELD):
        findings.append(_finding(f"live-{idx + 1}", "held", reason,
                                 "complete independent live and physical acceptance", {"observed": "unknown"}))
    exit_code = 2 if local_ok else 1
    return {"schema": "snowgloves.node-doctor.v1", "root": root_path,
            "status": "held" if local_ok else "fail", "exit_code": exit_code,
            "profile_ready": False, "inventory": observed, "journal": journal_status,
            "findings": findings}, exit_code


def doctor(root: str | os.PathLike[str]) -> dict[str, Any]:
    return _doctor_data(os.fspath(root))[0]


def _debug_data(root: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    if data is None:
        data, _ = _doctor_data(root)
    inv = data["inventory"]
    # Only allowlisted, nonsensitive diagnostic fields are emitted.
    return {"schema": "snowgloves.node-debug.v1", "root": data["root"],
            "source_digest": source_digest(),
            "inventory": {"platform": inv["platform"], "machine": inv["machine"],
                          "ram_bytes": inv["ram_bytes"], "disk": inv["disk"], "tools": inv["tools"]},
            "journal": data["journal"], "findings": data["findings"],
            "profile_ready": False}


def _parser() -> Parser:
    parser = Parser(prog="snowgloves node", description="Local-only Snow Gloves node bootstrap")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    for command in ("inspect", "doctor", "status"):
        item = sub.add_parser(command)
        item.add_argument("--root", default=os.getcwd())
    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--root", default=os.getcwd())
    plan_cmd.add_argument("--node", required=True)
    for command in ("apply", "resume", "rollback"):
        item = sub.add_parser(command)
        item.add_argument("--plan", required=True)
        item.add_argument("--digest", required=True)
    debug = sub.add_parser("debug")
    debug_sub = debug.add_subparsers(dest="debug_command", required=True, parser_class=Parser)
    collect = debug_sub.add_parser("collect")
    collect.add_argument("--root", default=os.getcwd())
    return parser


def _dispatch(args: argparse.Namespace) -> tuple[Any, int]:
    if args.command == "inspect":
        return inspect(args.root), 0
    if args.command == "plan":
        return make_plan(args.root, args.node), 0
    if args.command == "status":
        return journal.status(_canonical_root(args.root)), 0
    if args.command == "doctor":
        return _doctor_data(args.root)
    if args.command == "debug" and args.debug_command == "collect":
        doctor_data, exit_code = _doctor_data(args.root)
        return _debug_data(args.root, doctor_data), exit_code
    plan = _read_plan(args.plan)
    if type(args.digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", args.digest):
        journal._fail("review digest must be a lowercase SHA-256 digest")
    if plan["source_digest"] != source_digest():
        journal._fail("plan source is stale; create and review a fresh plan", 2)
    if args.command == "apply":
        return journal.apply(plan, args.digest), 0
    if args.command == "resume":
        return journal.apply(plan, args.digest, resume=True), 0
    return journal.rollback(plan, args.digest), 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        value, code = _dispatch(args)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return code
    except UsageError:
        print(json.dumps({"error": "invalid_arguments", "code": 3}), file=sys.stderr)
        return 3
    except journal.BootstrapError as exc:
        print(json.dumps({"error": "bootstrap_error", "code": exc.code,
                          "message": "request could not be completed"}), file=sys.stderr)
        return exc.code
    except (OSError, ValueError, TypeError):
        print(json.dumps({"error": "request_failed", "code": 1,
                          "message": "request could not be completed"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

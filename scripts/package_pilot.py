#!/usr/bin/env python3
"""Build or verify the explicit Snow Gloves local pilot package."""
from __future__ import annotations

import argparse
import ctypes
import errno
import gzip
import hashlib
import json
import os
import secrets
import stat
import sys
import tarfile
from typing import Any


PAYLOAD = (
    "bin/snowgloves",
    "scripts/node_bootstrap.py",
    "scripts/node_journal.py",
    "VERSION",
    "docs/LOCAL-MINI-PILOT.md",
    "scripts/install-local.sh",
)
RUNTIME = PAYLOAD[:-1]
MANIFEST = "SHA256SUMS"
MAX_FILE = 4_000_000
MAX_MANIFEST = 8192


class PackageError(Exception):
    pass


def _fail(message: str) -> None:
    raise PackageError(message)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(files: dict[str, bytes]) -> bytes:
    return "".join(f"{_sha(files[name])}  {name}\n" for name in sorted(files)).encode("ascii")


def _open_dir(path: str) -> int:
    if not os.path.isabs(path):
        _fail("directory must be absolute")
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in (item for item in path.split(os.sep) if item):
            if part in (".", ".."):
                _fail("directory path is not normalized")
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_file_at(dirfd: int, name: str, limit: int = MAX_FILE) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=dirfd)
    except OSError as exc:
        _fail(f"cannot safely read package file: {exc}")
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            _fail("package member is not a bounded regular file")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        if (len(data) > limit or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)):
            _fail("package member changed while being read")
        return bytes(data)
    finally:
        os.close(fd)


def _source_files() -> dict[str, bytes]:
    source_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    rootfd = _open_dir(source_root)
    files: dict[str, bytes] = {}
    try:
        for rel in PAYLOAD:
            pieces = rel.split("/")
            parent = os.dup(rootfd)
            try:
                for part in pieces[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=parent)
                    os.close(parent)
                    parent = nxt
                files[rel] = _read_file_at(parent, pieces[-1])
            finally:
                os.close(parent)
    finally:
        os.close(rootfd)
    return files


def _parse_manifest(raw: bytes, expected: tuple[str, ...]) -> dict[str, str]:
    if len(raw) > MAX_MANIFEST:
        _fail("checksum manifest exceeds size limit")
    try:
        text = raw.decode("ascii", "strict")
    except UnicodeError:
        _fail("checksum manifest is not ASCII")
    if not text.endswith("\n"):
        _fail("checksum manifest must end with newline")
    result: dict[str, str] = {}
    for line in text.splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            _fail("checksum manifest has invalid format")
        digest, name = line[:64], line[66:]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            _fail("checksum manifest digest is invalid")
        if name not in expected or name in result:
            _fail("checksum manifest has an unknown or duplicate member")
        result[name] = digest
    if list(result) != sorted(expected) or set(result) != set(expected):
        _fail("checksum manifest does not cover the exact payload")
    return result


def _verify_dir(path: str, members: tuple[str, ...] = PAYLOAD) -> tuple[dict[str, bytes], bytes]:
    absolute = os.path.abspath(path)
    fd = _open_dir(absolute)
    files: dict[str, bytes] = {}
    try:
        actual_names = set(os.listdir(fd))
        expected_names = {MANIFEST, *(name.split("/")[0] for name in members)}
        if actual_names != expected_names:
            _fail("package directory has missing or extra top-level objects")
        nested: dict[str, set[str]] = {}
        for rel in members:
            parts = rel.split("/")
            if len(parts) > 1:
                nested.setdefault(parts[0], set()).add(parts[1])
        for dirname, expected in nested.items():
            dfd = os.open(dirname, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                          dir_fd=fd)
            try:
                if set(os.listdir(dfd)) != expected:
                    _fail("package directory has missing or extra nested objects")
            finally:
                os.close(dfd)
        for rel in members:
            pieces = rel.split("/")
            parent = os.dup(fd)
            try:
                for part in pieces[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=parent)
                    os.close(parent)
                    parent = nxt
                files[rel] = _read_file_at(parent, pieces[-1])
            finally:
                os.close(parent)
        manifest = _read_file_at(fd, MANIFEST, MAX_MANIFEST)
        hashes = _parse_manifest(manifest, members)
        if any(_sha(content) != hashes[name] for name, content in files.items()):
            _fail("package checksum verification failed")
        return files, manifest
    finally:
        os.close(fd)


def _write_file(dirfd: int, name: str, data: bytes, mode: int) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 mode, dir_fd=dirfd)
    try:
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_into(stagefd: int, rel: str, data: bytes) -> None:
    pieces = rel.split("/")
    parent = os.dup(stagefd)
    try:
        for part in pieces[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=parent)
            except FileExistsError:
                pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            os.close(parent)
            parent = nxt
        mode = 0o755 if rel in ("bin/snowgloves", "scripts/install-local.sh") else 0o644
        _write_file(parent, pieces[-1], data, mode)
    finally:
        os.close(parent)


def _rename_noreplace(srcfd: int, src: str, dstfd: int, dst: str) -> None:
    """Use the host's atomic exclusive directory rename primitive."""
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
        _fail("this platform lacks an atomic no-clobber directory rename")
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def _tar_bytes(output_fd: int, name: str, files: dict[str, bytes], manifest: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=output_fd)
    try:
        with os.fdopen(os.dup(fd), "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                    all_files = dict(files)
                    all_files[MANIFEST] = manifest
                    for rel in (*PAYLOAD, MANIFEST):
                        data = all_files[rel]
                        info = tarfile.TarInfo(rel)
                        info.size = len(data)
                        info.mode = 0o755 if rel in ("bin/snowgloves", "scripts/install-local.sh") else 0o644
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.type = tarfile.REGTYPE
                        tar.addfile(info, __import__("io").BytesIO(data))
            raw.flush()
            os.fsync(raw.fileno())
    finally:
        os.close(fd)


def package(output: str) -> dict[str, Any]:
    files = _source_files()
    manifest = _manifest(files)
    parent_path, base = os.path.split(os.path.abspath(output))
    if not base or base in (".", ".."):
        _fail("output directory path is invalid")
    parentfd = _open_dir(parent_path)
    stage = f".{base}.stage-{secrets.token_hex(12)}"
    archive = base + ".tar.gz"
    tar_tmp = f".{archive}.tmp-{secrets.token_hex(12)}"
    try:
        try:
            os.stat(base, dir_fd=parentfd, follow_symlinks=False)
            _fail("output directory already exists")
        except FileNotFoundError:
            pass
        try:
            os.stat(archive, dir_fd=parentfd, follow_symlinks=False)
            _fail("output archive already exists")
        except FileNotFoundError:
            pass
        os.mkdir(stage, 0o700, dir_fd=parentfd)
        stagefd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parentfd)
        try:
            for rel, content in files.items():
                _copy_into(stagefd, rel, content)
            _write_file(stagefd, MANIFEST, manifest, 0o644)
            os.fsync(stagefd)
        finally:
            os.close(stagefd)
        _verify_dir(os.path.join(parent_path, stage))
        _tar_bytes(parentfd, tar_tmp, files, manifest)
        # Publish archive with a no-clobber hard link, then the verified directory
        # with an exclusive rename. Roll back our archive only if publication fails.
        os.link(tar_tmp, archive, src_dir_fd=parentfd, dst_dir_fd=parentfd, follow_symlinks=False)
        tar_stat = os.stat(archive, dir_fd=parentfd, follow_symlinks=False)
        os.unlink(tar_tmp, dir_fd=parentfd)
        try:
            _rename_noreplace(parentfd, stage, parentfd, base)
        except BaseException:
            try:
                current = os.stat(archive, dir_fd=parentfd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (tar_stat.st_dev, tar_stat.st_ino):
                    os.unlink(archive, dir_fd=parentfd)
            except OSError:
                pass
            raise
        os.fsync(parentfd)
        return {"status": "created", "directory": os.path.join(parent_path, base),
                "archive": os.path.join(parent_path, archive), "files": list(sorted(files)),
                "manifest_sha256": _sha(manifest)}
    except PackageError:
        raise
    except OSError as exc:
        _fail(f"package operation failed: {exc}")
    finally:
        # Failed private stages and temporary archives are retained as recovery
        # evidence. A later run uses a fresh random staging name.
        os.close(parentfd)


def verify(path: str) -> dict[str, Any]:
    files, manifest = _verify_dir(path)
    return {"status": "verified", "directory": os.path.abspath(path),
            "files": list(sorted(files)), "manifest_sha256": _sha(manifest)}


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="package_pilot.py", description="Build or verify a local pilot package")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output")
    group.add_argument("--verify")
    try:
        args = parser.parse_args(argv)
        result = package(args.output) if args.output else verify(args.verify)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0
    except ValueError:
        print(json.dumps({"error": "invalid_arguments", "code": 3}), file=sys.stderr)
        return 3
    except PackageError:
        print(json.dumps({"error": "package_operation_failed", "code": 1}), file=sys.stderr)
        return 1
    except OSError:
        print(json.dumps({"error": "package_operation_failed", "code": 1}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

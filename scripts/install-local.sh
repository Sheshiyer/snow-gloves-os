#!/bin/sh
set -eu

usage() {
  echo "usage: install-local.sh --prefix ABSOLUTE_PATH [--dry-run]" >&2
}

PREFIX=
DRY_RUN=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix)
      if [ "$#" -lt 2 ] || [ -n "$PREFIX" ]; then usage; exit 3; fi
      PREFIX=$2
      shift 2
      ;;
    --dry-run)
      if [ "$DRY_RUN" -eq 1 ]; then usage; exit 3; fi
      DRY_RUN=1
      shift
      ;;
    *) usage; exit 3 ;;
  esac
done

if [ -z "$PREFIX" ]; then usage; exit 3; fi
case "$PREFIX" in /*) ;; *) usage; exit 3 ;; esac

if ! command -v python3 >/dev/null 2>&1; then
  echo '{"error":"python3_10_required","code":1}' >&2
  exit 1
fi
if ! python3 -B -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo '{"error":"python3_10_required","code":1}' >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -L)
SOURCE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -L)
exec python3 -B - "$SOURCE_ROOT" "$PREFIX" "$DRY_RUN" <<'PY'
import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
import sys

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

class InstallError(Exception):
    pass

def fail(message):
    raise InstallError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def open_dir(path):
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        fail("path must be absolute and normalized")
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in (x for x in path.split(os.sep) if x):
            if part in (".", ".."):
                fail("dot path components are forbidden")
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise

def read_at(dirfd, name, limit=MAX_FILE):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=dirfd)
    except OSError as exc:
        fail("package contains an unreadable or unsafe file")
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            fail("package member is not a bounded regular file")
        data = bytearray()
        while len(data) <= limit:
            part = os.read(fd, min(65536, limit + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
        if (len(data) > limit or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)):
            fail("package member changed while being verified")
        return bytes(data)
    finally:
        os.close(fd)

def parse_manifest(raw, members):
    try:
        text = raw.decode("ascii", "strict")
    except UnicodeError:
        fail("checksum manifest is invalid")
    if len(raw) > MAX_MANIFEST or not text.endswith("\n"):
        fail("checksum manifest is invalid")
    result = {}
    for line in text.splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            fail("checksum manifest is invalid")
        digest, name = line[:64], line[66:]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            fail("checksum manifest is invalid")
        if name not in members or name in result:
            fail("checksum manifest contains an unexpected file")
        result[name] = digest
    if list(result) != sorted(members) or set(result) != set(members):
        fail("checksum manifest is incomplete")
    return result

def read_payload(rootfd):
    actual_top = set(os.listdir(rootfd))
    expected_top = {"bin", "scripts", "docs", "VERSION", MANIFEST}
    if actual_top != expected_top:
        fail("source package has missing or extra top-level members")
    expected_nested = {"bin": {"snowgloves"},
                       "scripts": {"node_bootstrap.py", "node_journal.py", "install-local.sh"},
                       "docs": {"LOCAL-MINI-PILOT.md"}}
    for dirname, expected in expected_nested.items():
        dfd = os.open(dirname, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=rootfd)
        try:
            if set(os.listdir(dfd)) != expected:
                fail("source package has missing or extra nested members")
        finally:
            os.close(dfd)
    files = {}
    for rel in PAYLOAD:
        parts = rel.split("/")
        parent = os.dup(rootfd)
        try:
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                os.close(parent)
                parent = nxt
            files[rel] = read_at(parent, parts[-1])
        finally:
            os.close(parent)
    manifest = read_at(rootfd, MANIFEST, MAX_MANIFEST)
    hashes = parse_manifest(manifest, PAYLOAD)
    if any(sha(data) != hashes[name] for name, data in files.items()):
        fail("package checksum verification failed")
    return files

def rename_exclusive(srcfd, src, dstfd, dst):
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        fn = libc.renameat2
        flag = 1
    elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        fn = libc.renameatx_np
        flag = 4
    else:
        fail("platform lacks atomic no-clobber directory publication")
    fn.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    fn.restype = ctypes.c_int
    if fn(srcfd, os.fsencode(src), dstfd, os.fsencode(dst), flag) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))

def read_installed(dirfd, expected):
    names = set(os.listdir(dirfd))
    if names != {"bin", "scripts", "docs", "VERSION", MANIFEST}:
        return False
    actual = {}
    expected_nested = {"bin": {"snowgloves"}, "scripts": {"node_bootstrap.py", "node_journal.py"},
                       "docs": {"LOCAL-MINI-PILOT.md"}}
    if stat.S_IMODE(os.fstat(dirfd).st_mode) != 0o700:
        return False
    for dirname, expected_names in expected_nested.items():
        try:
            dfd = os.open(dirname, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                          dir_fd=dirfd)
        except OSError:
            return False
        try:
            if set(os.listdir(dfd)) != expected_names or stat.S_IMODE(os.fstat(dfd).st_mode) != 0o700:
                return False
        finally:
            os.close(dfd)
    for rel in RUNTIME:
        parts = rel.split("/")
        parent = os.dup(dirfd)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                os.close(parent)
                parent = child
            actual[rel] = read_at(parent, parts[-1])
            st = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            wanted_mode = 0o700 if rel == "bin/snowgloves" else 0o600
            if stat.S_IMODE(st.st_mode) != wanted_mode:
                return False
        except OSError:
            return False
        finally:
            os.close(parent)
    try:
        manifest = read_at(dirfd, MANIFEST, MAX_MANIFEST)
        hashes = parse_manifest(manifest, RUNTIME)
    except (InstallError, OSError):
        return False
    try:
        manifest_st = os.stat(MANIFEST, dir_fd=dirfd, follow_symlinks=False)
    except OSError:
        return False
    return (stat.S_IMODE(manifest_st.st_mode) == 0o600 and actual == expected and manifest == b"".join(
        f"{sha(expected[name])}  {name}\n".encode("ascii") for name in sorted(RUNTIME)
    ) and all(sha(actual[name]) == hashes[name] for name in RUNTIME))

def write_at(dirfd, name, data, mode):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 mode, dir_fd=dirfd)
    try:
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            view = view[count:]
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)

def install_tree(stagefd, files):
    for rel in RUNTIME:
        parts = rel.split("/")
        parent = os.dup(stagefd)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                os.close(parent)
                parent = child
            mode = 0o700 if rel == "bin/snowgloves" else 0o600
            write_at(parent, parts[-1], files[rel], mode)
        finally:
            os.close(parent)
    manifest = "".join(f"{sha(files[name])}  {name}\n" for name in sorted(RUNTIME)).encode("ascii")
    write_at(stagefd, MANIFEST, manifest, 0o600)
    os.fsync(stagefd)

def open_parent_create(path, create):
    parent, leaf = os.path.split(path)
    if not leaf or leaf in (".", "..") or not parent:
        fail("prefix path is invalid")
    if not create:
        return open_dir(parent), leaf
    # Walk from root so each missing parent is created beneath a pinned,
    # no-follow directory descriptor.
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in (part for part in parent.split(os.sep) if part):
            try:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(component, 0o700, dir_fd=fd)
                os.fsync(fd)
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd, leaf
    except BaseException:
        os.close(fd)
        raise

def main():
    source, prefix, dry = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
    if not os.path.isabs(prefix) or os.path.normpath(prefix) != prefix:
        fail("prefix must be absolute and normalized")
    source_abs = os.path.abspath(source)
    if os.path.commonpath((source_abs, prefix)) == source_abs:
        fail("prefix cannot be inside the verified source package")
    source_rootfd = open_dir(source)
    try:
        files = read_payload(source_rootfd)  # Verify every payload before any writes.
    finally:
        os.close(source_rootfd)
    prefix_parent = os.path.dirname(prefix)
    try:
        parentfd, leaf = open_parent_create(prefix, create=False)
    except FileNotFoundError:
        if dry:
            print(json.dumps({"status": "would-install", "prefix": prefix}, sort_keys=True))
            return 0
        parentfd, leaf = open_parent_create(prefix, create=True)
    try:
        try:
            existing = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parentfd)
        except FileNotFoundError:
            existing = -1
        except OSError:
            fail("existing prefix is not a safe directory")
        if existing >= 0:
            try:
                if read_installed(existing, {name: files[name] for name in RUNTIME}):
                    print(json.dumps({"status": "already-installed", "prefix": prefix}, sort_keys=True))
                    return 0
                fail("existing prefix differs from the verified package")
            finally:
                os.close(existing)
        if dry:
            print(json.dumps({"status": "would-install", "prefix": prefix}, sort_keys=True))
            return 0
        stage = "." + leaf + ".stage-" + secrets.token_hex(12)
        try:
            os.mkdir(stage, 0o700, dir_fd=parentfd)
            stagefd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parentfd)
            try:
                install_tree(stagefd, files)
            finally:
                os.close(stagefd)
            rename_exclusive(parentfd, stage, parentfd, leaf)
        except BaseException:
            # Keep the private staging tree as evidence instead of deleting a
            # path that may have been changed during the failed publication.
            raise
        os.fsync(parentfd)
        print(json.dumps({"status": "installed", "prefix": prefix}, sort_keys=True))
        return 0
    finally:
        os.close(parentfd)

try:
    raise SystemExit(main())
except InstallError:
    print(json.dumps({"error": "installation_refused", "code": 1}), file=sys.stderr)
    raise SystemExit(1)
except (OSError, ValueError, TypeError):
    print(json.dumps({"error": "installation_failed", "code": 1}), file=sys.stderr)
    raise SystemExit(1)
PY

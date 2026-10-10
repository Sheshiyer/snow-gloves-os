#!/usr/bin/python3
"""Install the macOS Snow Gloves restricted, key-only SSH surface.

The installer is dry-run by default.  ``--apply`` is intentionally narrow:
it can install only this package's marked files, a root-owned public snapshot,
one bounded ``Match`` block, and one membership in ``com.apple.access_ssh``.
It never creates accounts, accepts passwords, restarts sshd, or changes global
SSH policy.
"""

from __future__ import print_function

import argparse
import base64
import grp
import ipaddress
import json
import os
import platform
import pwd
import re
import secrets
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.dont_write_bytecode = True

try:  # Direct execution and package import both matter for this standalone script.
    from . import restricted_ssh
except ImportError:  # pragma: no cover - exercised when installed as a script
    import restricted_ssh  # type: ignore


DISPATCHER_DESTINATION = Path("/usr/local/libexec/snowgloves-restricted-ssh.py")
SSHD_CONFIG = Path("/etc/ssh/sshd_config")
CONFIG_DIR = Path("/etc/ssh/snowgloves")
SNAPSHOT_BASE = Path("/Users/Shared/snowgloves-readonly")
REMOTE_LOGIN_GROUP = "com.apple.access_ssh"

SSHD = "/usr/sbin/sshd"
DSMEMBERUTIL = "/usr/bin/dsmemberutil"
DSEDITGROUP = "/usr/sbin/dseditgroup"
GIT = "/usr/bin/git"

MAX_PUBLIC_KEY_BYTES = 8192
MAX_GIT_TREE_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_FILES = 5000
MAX_SNAPSHOT_FILE_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_MANAGED_FILE_BYTES = 1024 * 1024

_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_COMMENT_RE = re.compile(r"^[A-Za-z0-9@._+=:-]{1,128}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_SENSITIVE_COMPONENTS = {
    ".git",
    ".planning",
    "_audit",
    "_runtime",
    "credential",
    "credentials",
    "decision",
    "decisions",
    "instance",
    "instances",
    "key",
    "keys",
    "node",
    "nodes",
    "planning",
    "private",
    "receipt",
    "receipts",
    "secret",
    "secrets",
    "tenant",
    "tenants",
}
_TEXT_EXTENSIONS = {
    ".bash",
    ".c",
    ".cfg",
    ".cjs",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".go",
    ".h",
    ".htm",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".svg",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}
_ALLOWED_PREFIXES = (
    "adapters/",
    "agents/",
    "apps/infra-block/src/",
    "catalog/",
    "docs/",
    "scripts/",
    "skills/",
)
_ALLOWED_TOP_LEVEL = {"AGENTS.md", "README.md"}
_DISPATCHER_MARKER = b"# snowgloves-restricted-ssh-dispatcher managed\n"
_AUTHORIZATION_MARKER = "# snowgloves-restricted-ssh managed key for "
_BASE_MARKER = b"snowgloves-restricted-ssh snapshot base\n"
_USER_MARKER_PREFIX = b"snowgloves-restricted-ssh snapshot owner="
_PRIVATE_KEY_MARKER = re.compile(br"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----")
_SENSITIVE_ASSIGNMENT = re.compile(
    br"(?im)^[ \t]*[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY|PRIVATE[_-]?KEY)"
    br"[A-Z0-9_]*[ \t]*[:=][ \t]*[\"']?[^ \t\r\n#]{8,}"
)


class InstallerError(Exception):
    """An administrator-facing failure.  No remote SSH caller sees this text."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


class CommandRunner:
    """Small command boundary that makes all system commands inspectable in tests."""

    def run(
        self,
        args: Sequence[str],
        cwd: Optional[Path] = None,
        timeout: float = 30.0,
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                list(args),
                check=False,
                close_fds=True,
                cwd=str(cwd) if cwd is not None else None,
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstallerError("required local command could not run") from exc
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class FileMetadata:
    mode: int
    uid: int
    gid: int
    size: int
    device: int
    inode: int


class FileOps:
    """Filesystem boundary.  Tests can emulate root ownership without root."""

    def lexists(self, path: Path) -> bool:
        return os.path.lexists(str(path))

    def metadata(self, path: Path) -> FileMetadata:
        try:
            item = os.lstat(str(path))
        except OSError as exc:
            raise InstallerError("required filesystem path is unavailable") from exc
        return FileMetadata(
            mode=item.st_mode,
            uid=item.st_uid,
            gid=item.st_gid,
            size=item.st_size,
            device=item.st_dev,
            inode=item.st_ino,
        )

    def read_bytes(self, path: Path) -> bytes:
        try:
            with open(str(path), "rb") as handle:
                return handle.read()
        except OSError as exc:
            raise InstallerError("cannot read managed file") from exc

    def mkdir(self, path: Path, mode: int) -> None:
        try:
            os.mkdir(str(path), mode)
        except OSError as exc:
            raise InstallerError("cannot create managed directory") from exc

    def chmod(self, path: Path, mode: int) -> None:
        try:
            os.chmod(str(path), mode)
        except OSError as exc:
            raise InstallerError("cannot set managed permissions") from exc

    def set_owner(self, path: Path, uid: int, gid: int) -> None:
        try:
            os.chown(str(path), uid, gid)
        except OSError as exc:
            raise InstallerError("cannot set managed ownership") from exc

    def write_new(self, path: Path, data: bytes, mode: int, uid: int, gid: int) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(str(path), flags, mode)
        except OSError as exc:
            raise InstallerError("managed target collision") from exc
        try:
            _write_all(descriptor, data)
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        except OSError as exc:
            raise InstallerError("cannot write managed file") from exc
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.set_owner(path, uid, gid)

    def atomic_replace(self, path: Path, data: bytes, mode: int, uid: int, gid: int) -> None:
        temporary = path.parent / (".{0}.snowgloves-tmp-{1}".format(path.name, secrets.token_hex(8)))
        self.write_new(temporary, data, mode, uid, gid)
        try:
            os.replace(str(temporary), str(path))
        except OSError as exc:
            try:
                self.unlink(temporary)
            except InstallerError:
                pass
            raise InstallerError("cannot replace managed file") from exc

    def rename(self, source: Path, destination: Path) -> None:
        try:
            os.rename(str(source), str(destination))
        except OSError as exc:
            raise InstallerError("cannot move managed snapshot") from exc

    def unlink(self, path: Path) -> None:
        try:
            os.unlink(str(path))
        except OSError as exc:
            raise InstallerError("cannot remove managed file") from exc

    def rmdir(self, path: Path) -> None:
        try:
            os.rmdir(str(path))
        except OSError as exc:
            raise InstallerError("cannot remove managed directory") from exc

    def listdir(self, path: Path) -> List[Path]:
        try:
            return [path / item.name for item in os.scandir(str(path))]
        except OSError as exc:
            raise InstallerError("cannot inspect managed directory") from exc


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


@dataclass(frozen=True)
class Account:
    name: str
    uid: int
    gid: int
    shell: str


class HostOps:
    """The macOS identity/group boundary used only by --apply."""

    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def is_darwin(self) -> bool:
        return platform.system() == "Darwin"

    def effective_uid(self) -> int:
        return os.geteuid()

    def lookup_user(self, username: str) -> Account:
        try:
            record = pwd.getpwnam(username)
        except KeyError as exc:
            raise InstallerError("requested account does not exist") from exc
        return Account(record.pw_name, record.pw_uid, record.pw_gid, record.pw_shell)

    def _membership(self, username: str, group_name: str) -> bool:
        result = self.runner.run(
            [DSMEMBERUTIL, "checkmembership", "-U", username, "-G", group_name],
            timeout=10,
        )
        if result.returncode == 0:
            message = result.stdout.strip()
            if message == b"user is a member of the group":
                return True
            if message == b"user is not a member of the group":
                return False
        raise InstallerError("cannot verify macOS group membership")

    def user_is_admin(self, username: str) -> bool:
        try:
            admin = grp.getgrnam("admin")
            account = pwd.getpwnam(username)
            if username in admin.gr_mem or account.pw_gid == admin.gr_gid:
                return True
        except KeyError:
            # dsmemberutil is the authoritative macOS check below.
            pass
        return self._membership(username, "admin")

    def group_exists(self, group_name: str) -> bool:
        try:
            grp.getgrnam(group_name)
        except KeyError:
            return False
        return True

    def group_has_member(self, group_name: str, username: str) -> bool:
        return self._membership(username, group_name)

    def add_group_member(self, group_name: str, username: str) -> None:
        result = self.runner.run(
            [DSEDITGROUP, "-o", "edit", "-a", username, "-t", "user", group_name],
            timeout=20,
        )
        if result.returncode != 0:
            raise InstallerError("cannot add account to existing Remote Login group")

    def remove_group_member(self, group_name: str, username: str) -> None:
        result = self.runner.run(
            [DSEDITGROUP, "-o", "edit", "-d", username, "-t", "user", group_name],
            timeout=20,
        )
        if result.returncode != 0:
            raise InstallerError("cannot roll back Remote Login group membership")


@dataclass(frozen=True)
class InstallPaths:
    dispatcher_source: Path
    dispatcher_destination: Path
    sshd_config: Path
    config_dir: Path
    snapshot_base: Path

    @classmethod
    def production(cls) -> "InstallPaths":
        return cls(
            dispatcher_source=Path(__file__).with_name("restricted_ssh.py"),
            dispatcher_destination=DISPATCHER_DESTINATION,
            sshd_config=SSHD_CONFIG,
            config_dir=CONFIG_DIR,
            snapshot_base=SNAPSHOT_BASE,
        )

    def config_path(self, username: str) -> Path:
        return self.config_dir / (username + ".json")

    def authorized_keys_path(self, username: str) -> Path:
        return self.config_dir / (username + ".authorized_keys")

    def snapshot_user_dir(self, username: str) -> Path:
        return self.snapshot_base / username

    def snapshot_root(self, username: str) -> Path:
        return self.snapshot_user_dir(username) / "platform"


@dataclass(frozen=True)
class InstallOptions:
    username: str
    public_key_file: Path
    source_ip: str
    source_checkout: Path
    apply: bool = False
    control_user: Optional[str] = None


@dataclass(frozen=True)
class SnapshotEntry:
    relative_path: str
    data: bytes


@dataclass(frozen=True)
class InstallPlan:
    options: InstallOptions
    public_key: str
    source_ip: str
    commit: str
    entries: Tuple[SnapshotEntry, ...]
    config_data: bytes
    authorized_keys_data: bytes
    dispatcher_data: bytes

    @property
    def snapshot_bytes(self) -> int:
        return sum(len(entry.data) for entry in self.entries)


@dataclass
class InstallReport:
    applied: bool
    lines: List[str]


class RollbackStack:
    """Exact, recorded compensations only; no broad deletion commands."""

    def __init__(self) -> None:
        self._rollback: List[Tuple[str, Callable[[], None]]] = []
        self._cleanup: List[Tuple[str, Callable[[], None]]] = []

    def add_rollback(self, label: str, action: Callable[[], None]) -> None:
        self._rollback.append((label, action))

    def add_cleanup(self, label: str, action: Callable[[], None]) -> None:
        self._cleanup.append((label, action))

    def rollback(self) -> List[str]:
        failures: List[str] = []
        for label, action in reversed(self._rollback):
            try:
                action()
            except Exception:
                failures.append(label)
        return failures

    def commit(self) -> List[str]:
        failures: List[str] = []
        for label, action in self._cleanup:
            try:
                action()
            except Exception:
                failures.append(label)
        return failures


def validate_username(username: str) -> str:
    if not isinstance(username, str) or not _USERNAME_RE.fullmatch(username) or username == "root":
        raise InstallerError("user must be a safe non-root local account name")
    return username


def validate_source_ip(source_ip: str) -> str:
    try:
        parsed = ipaddress.ip_address(source_ip)
    except ValueError as exc:
        raise InstallerError("source IP must be one IPv4 address in 100.64.0.0/10") from exc
    network = ipaddress.ip_network("100.64.0.0/10")
    if parsed.version != 4 or parsed not in network:
        raise InstallerError("source IP must be one IPv4 address in 100.64.0.0/10")
    return str(parsed)


def validate_public_key_bytes(data: bytes) -> str:
    """Accept exactly one bare ssh-ed25519 key and one harmless optional comment."""

    if not data or len(data) > MAX_PUBLIC_KEY_BYTES or b"\n" in data or b"\r" in data:
        raise InstallerError("public key must be one newline-free ssh-ed25519 line")
    try:
        value = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise InstallerError("public key must be ASCII") from exc
    parts = value.split(" ")
    if len(parts) not in (2, 3) or any(part == "" for part in parts):
        raise InstallerError("public key must not contain options or multiple keys")
    key_type, encoded = parts[0], parts[1]
    if key_type != "ssh-ed25519":
        raise InstallerError("only ssh-ed25519 public keys are allowed")
    if len(parts) == 3 and not _COMMENT_RE.fullmatch(parts[2]):
        raise InstallerError("public key comment is not harmless")
    try:
        wire = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise InstallerError("public key payload is invalid") from exc
    if wire != b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + wire[-32:] or len(wire) != 51:
        raise InstallerError("public key payload is not an ed25519 public key")
    return value


def read_public_key(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise InstallerError("cannot read public key file") from exc
    # A normal .pub file has one terminal newline; embedded/multiple lines still reject.
    if data.endswith(b"\n"):
        data = data[:-1]
    return validate_public_key_bytes(data)


def _source_checkout_path(path: Path) -> Path:
    absolute = Path(os.path.abspath(str(path)))
    try:
        item = os.lstat(str(absolute))
    except OSError as exc:
        raise InstallerError("source checkout does not exist") from exc
    if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
        raise InstallerError("source checkout must be a real directory, not a symlink")
    return absolute


def _git(
    runner: CommandRunner,
    source_checkout: Path,
    args: Sequence[str],
    timeout: float = 30.0,
) -> CommandResult:
    result = runner.run(
        [GIT, "-c", "safe.directory={0}".format(source_checkout), "-C", str(source_checkout), *args],
        timeout=timeout,
    )
    if result.returncode != 0:
        raise InstallerError("source checkout is not a readable committed Git checkout")
    return result


def _validate_git_path(raw_path: bytes) -> str:
    try:
        path = raw_path.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise InstallerError("Git tree has a non-UTF-8 path") from exc
    if not path or path.startswith("/") or "\\" in path:
        raise InstallerError("Git tree has an unsafe path")
    parts = path.split("/")
    for part in parts:
        if not part or part in (".", "..") or any(ord(char) < 32 or ord(char) == 127 for char in part):
            raise InstallerError("Git tree has an unsafe path")
    return path


def _is_selected_snapshot_path(path: str) -> bool:
    parts = path.split("/")
    lower_parts = [part.lower() for part in parts]
    if any(part.startswith(".") or part in _SENSITIVE_COMPONENTS or Path(part).stem in _SENSITIVE_COMPONENTS for part in lower_parts):
        return False
    if parts[-1].lower() == "isa.md":
        return False
    if path not in _ALLOWED_TOP_LEVEL and not any(path.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        return False
    if not all(_SAFE_COMPONENT_RE.fullmatch(part) for part in parts):
        return False
    return Path(parts[-1]).suffix.lower() in _TEXT_EXTENSIONS


def _is_text_blob(data: bytes) -> bool:
    if b"\x00" in data or _PRIVATE_KEY_MARKER.search(data) or _SENSITIVE_ASSIGNMENT.search(data):
        return False
    try:
        decoded = data.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return False
    return not any(ord(char) < 32 and char not in "\t\r\n" for char in decoded)


def collect_snapshot_entries(
    source_checkout: Path,
    runner: CommandRunner,
) -> Tuple[str, Tuple[SnapshotEntry, ...]]:
    """Read only selected committed blobs, never the working tree or .git."""

    source = _source_checkout_path(source_checkout)
    commit_result = _git(runner, source, ["rev-parse", "--verify", "HEAD^{commit}"])
    try:
        commit = commit_result.stdout.decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc:
        raise InstallerError("Git HEAD is invalid") from exc
    if not _COMMIT_RE.fullmatch(commit):
        raise InstallerError("Git HEAD is invalid")

    tree_result = _git(runner, source, ["ls-tree", "-r", "-z", "--full-tree", commit])
    if len(tree_result.stdout) > MAX_GIT_TREE_BYTES:
        raise InstallerError("Git tree listing exceeds the snapshot bound")

    selected: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for record in tree_result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = header.split(b" ", 2)
        except ValueError as exc:
            raise InstallerError("Git tree listing is malformed") from exc
        path = _validate_git_path(raw_path)
        if object_type != b"blob" or mode not in (b"100644", b"100755"):
            # Symlink blobs are mode 120000 and are intentionally not copied.
            continue
        try:
            object_text = object_id.decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise InstallerError("Git tree object is invalid") from exc
        if not _COMMIT_RE.fullmatch(object_text):
            raise InstallerError("Git tree object is invalid")
        if not _is_selected_snapshot_path(path):
            continue
        if path in seen:
            raise InstallerError("Git tree has duplicate snapshot path")
        seen.add(path)
        selected.append((path, object_text))
        if len(selected) > MAX_SNAPSHOT_FILES:
            raise InstallerError("snapshot file count exceeds the bound")

    if not selected:
        raise InstallerError("no eligible public source files found at committed HEAD")

    entries: List[SnapshotEntry] = []
    total = 0
    for path, object_id in sorted(selected):
        size_result = _git(runner, source, ["cat-file", "-s", object_id])
        try:
            size_text = size_result.stdout.decode("ascii", "strict").strip()
            size = int(size_text, 10)
        except (UnicodeDecodeError, ValueError) as exc:
            raise InstallerError("Git blob size is invalid") from exc
        if size < 0 or size > MAX_SNAPSHOT_FILE_BYTES or total + size > MAX_SNAPSHOT_BYTES:
            raise InstallerError("snapshot byte bound exceeded")
        blob_result = _git(runner, source, ["cat-file", "blob", object_id])
        data = blob_result.stdout
        if len(data) != size:
            raise InstallerError("snapshot blob size changed")
        if not _is_text_blob(data):
            # Omit binary/credential-like content instead of publishing it.
            continue
        total += len(data)
        entries.append(SnapshotEntry(path, data))
    if not entries:
        raise InstallerError("no safe public text blobs remain")
    return commit, tuple(entries)


def build_config_data(username: str, snapshot_root: Path, commit: str) -> bytes:
    payload = {
        "allowed_root": str(snapshot_root),
        "managed_by": restricted_ssh.MANAGED_BY,
        "scope": restricted_ssh.SCOPE,
        "snapshot_commit": commit,
        "user": username,
        "version": restricted_ssh.CONFIG_VERSION,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_authorized_keys_data(username: str, source_ip: str, public_key: str) -> bytes:
    command = "/usr/bin/python3 -I {0}".format(DISPATCHER_DESTINATION)
    line = 'restrict,from="{0}",command="{1}" {2}'.format(source_ip, command, public_key)
    return ("{0}{1}\n{2}\n".format(_AUTHORIZATION_MARKER, username, line)).encode("ascii")


def _match_markers(username: str) -> Tuple[bytes, bytes]:
    begin = "# BEGIN snowgloves-restricted-ssh {0}".format(username).encode("ascii")
    end = "# END snowgloves-restricted-ssh {0}".format(username).encode("ascii")
    return begin, end


def build_match_block(username: str, source_ip: str) -> bytes:
    begin, end = _match_markers(username)
    command = "/usr/bin/python3 -I {0}".format(DISPATCHER_DESTINATION)
    lines = [
        begin,
        "Match User {0}".format(username).encode("ascii"),
        "    AuthorizedKeysFile {0}".format(CONFIG_DIR / (username + ".authorized_keys")).encode("ascii"),
        "    ForceCommand {0}".format(command).encode("ascii"),
        b"    AuthenticationMethods publickey",
        b"    PasswordAuthentication no",
        b"    KbdInteractiveAuthentication no",
        b"    PermitTTY no",
        b"    DisableForwarding yes",
        b"    PermitUserRC no",
        end,
    ]
    return b"\n".join(lines) + b"\n"


def render_sshd_config(original: bytes, username: str, source_ip: str) -> bytes:
    """Append or replace only our user's bounded terminal Match block."""

    begin, end = _match_markers(username)
    block = build_match_block(username, source_ip)
    begin_count = original.count(begin)
    end_count = original.count(end)
    if begin_count == 0 and end_count == 0:
        separator = b"" if not original or original.endswith(b"\n") else b"\n"
        return original + separator + block
    if begin_count != 1 or end_count != 1:
        raise InstallerError("unsafe or duplicate managed SSH Match block")

    begin_at = original.find(begin)
    end_at = original.find(end, begin_at + len(begin))
    if begin_at < 0 or end_at < begin_at:
        raise InstallerError("unsafe managed SSH Match block")
    if begin_at and original[begin_at - 1 : begin_at] != b"\n":
        raise InstallerError("unsafe managed SSH Match block")

    line_end = original.find(b"\n", end_at)
    replace_end = len(original) if line_end < 0 else line_end + 1
    trailing = original[replace_end:]
    if trailing.strip(b" \t\r\n"):
        raise InstallerError("managed SSH Match block is not at end of sshd_config")
    return original[:begin_at] + block + trailing


def _is_root_owned_readonly(item: FileMetadata) -> bool:
    return item.uid == 0 and (item.mode & 0o022) == 0


def _require_secure_directory(fs: FileOps, path: Path) -> None:
    item = fs.metadata(path)
    if stat.S_ISLNK(item.mode) or not stat.S_ISDIR(item.mode) or not _is_root_owned_readonly(item):
        raise InstallerError("unsafe managed directory")


def _require_shared_parent(fs: FileOps, path: Path) -> None:
    item = fs.metadata(path)
    if (
        stat.S_ISLNK(item.mode)
        or not stat.S_ISDIR(item.mode)
        or item.uid != 0
        or not (item.mode & stat.S_ISVTX)
    ):
        raise InstallerError("snapshot parent is not the expected root-owned sticky directory")


def _require_secure_regular(fs: FileOps, path: Path, maximum_size: int = MAX_MANAGED_FILE_BYTES) -> FileMetadata:
    item = fs.metadata(path)
    if (
        stat.S_ISLNK(item.mode)
        or not stat.S_ISREG(item.mode)
        or not _is_root_owned_readonly(item)
        or item.size > maximum_size
    ):
        raise InstallerError("unsafe managed file")
    return item


def _ensure_directory(
    fs: FileOps,
    path: Path,
    rollback: RollbackStack,
    allow_sticky_shared_parent: bool = False,
) -> None:
    if fs.lexists(path):
        _require_secure_directory(fs, path)
        return
    if allow_sticky_shared_parent:
        _require_shared_parent(fs, path.parent)
    else:
        _require_secure_directory(fs, path.parent)
    fs.mkdir(path, 0o755)
    fs.chmod(path, 0o755)
    fs.set_owner(path, 0, 0)
    _require_secure_directory(fs, path)

    def remove_empty_directory() -> None:
        if fs.lexists(path):
            _require_secure_directory(fs, path)
            fs.rmdir(path)

    rollback.add_rollback("remove created directory {0}".format(path), remove_empty_directory)


def _read_managed_file(fs: FileOps, path: Path) -> Tuple[bytes, FileMetadata]:
    item = _require_secure_regular(fs, path)
    data = fs.read_bytes(path)
    if len(data) != item.size:
        raise InstallerError("managed file changed during read")
    return data, item


def _install_managed_file(
    fs: FileOps,
    path: Path,
    expected: bytes,
    mode: int,
    managed_predicate: Callable[[bytes], bool],
    rollback: RollbackStack,
) -> bool:
    """Create or update only an existing file demonstrably owned by this package."""

    before_data: Optional[bytes] = None
    before_metadata: Optional[FileMetadata] = None
    if fs.lexists(path):
        before_data, before_metadata = _read_managed_file(fs, path)
        if not managed_predicate(before_data):
            raise InstallerError("refusing to replace unrelated existing file")
        if before_data == expected:
            return False
        fs.atomic_replace(path, expected, mode, 0, 0)
    else:
        _require_secure_directory(fs, path.parent)
        fs.write_new(path, expected, mode, 0, 0)

    _require_secure_regular(fs, path, max(MAX_MANAGED_FILE_BYTES, len(expected)))

    def restore() -> None:
        if not fs.lexists(path):
            raise InstallerError("managed file vanished before rollback")
        current, _ = _read_managed_file(fs, path)
        if current != expected:
            raise InstallerError("managed file changed before rollback")
        if before_data is None:
            fs.unlink(path)
        else:
            assert before_metadata is not None
            fs.atomic_replace(path, before_data, stat.S_IMODE(before_metadata.mode), before_metadata.uid, before_metadata.gid)

    rollback.add_rollback("restore managed file {0}".format(path), restore)
    return True


def _create_or_require_marker(
    fs: FileOps,
    path: Path,
    expected: bytes,
    rollback: RollbackStack,
) -> None:
    if fs.lexists(path):
        data, _ = _read_managed_file(fs, path)
        if data != expected:
            raise InstallerError("snapshot path collision is not owned by this package")
        return
    _require_secure_directory(fs, path.parent)
    fs.write_new(path, expected, 0o644, 0, 0)

    def remove_marker() -> None:
        if not fs.lexists(path):
            return
        data, _ = _read_managed_file(fs, path)
        if data != expected:
            raise InstallerError("snapshot marker changed before rollback")
        fs.unlink(path)

    rollback.add_rollback("remove snapshot marker {0}".format(path), remove_marker)


def _safe_remove_tree(fs: FileOps, root: Path, expected_parent: Path) -> None:
    """Remove one exact root-owned tree; never follow links or accept broad roots."""

    if root.parent != expected_parent:
        raise InstallerError("unsafe managed cleanup target")
    _require_secure_directory(fs, root)
    for child in fs.listdir(root):
        item = fs.metadata(child)
        if stat.S_ISLNK(item.mode) or not _is_root_owned_readonly(item):
            raise InstallerError("unsafe managed cleanup tree")
        if stat.S_ISDIR(item.mode):
            _safe_remove_tree(fs, child, root)
        elif stat.S_ISREG(item.mode):
            fs.unlink(child)
        else:
            raise InstallerError("unsafe managed cleanup tree")
    fs.rmdir(root)


def _validate_snapshot_tree(fs: FileOps, root: Path, count: int = 0) -> int:
    """Fail closed before replacing an existing package-owned snapshot."""

    _require_secure_directory(fs, root)
    for child in fs.listdir(root):
        count += 1
        if count > MAX_SNAPSHOT_FILES * 2:
            raise InstallerError("existing snapshot exceeds safety bound")
        item = fs.metadata(child)
        if stat.S_ISLNK(item.mode) or not _is_root_owned_readonly(item):
            raise InstallerError("existing snapshot contains unsafe entry")
        if stat.S_ISDIR(item.mode):
            count = _validate_snapshot_tree(fs, child, count)
        elif not stat.S_ISREG(item.mode):
            raise InstallerError("existing snapshot contains unsafe entry")
    return count


def _unique_child(fs: FileOps, parent: Path, prefix: str, suffix: str = "") -> Path:
    for _ in range(16):
        candidate = parent / (prefix + secrets.token_hex(8) + suffix)
        if not fs.lexists(candidate):
            return candidate
    raise InstallerError("cannot allocate a safe managed temporary path")


def _write_snapshot_staging(
    fs: FileOps,
    user_directory: Path,
    entries: Iterable[SnapshotEntry],
) -> Path:
    staging = _unique_child(fs, user_directory, ".platform.staging-")
    _require_secure_directory(fs, user_directory)
    fs.mkdir(staging, 0o755)
    fs.chmod(staging, 0o755)
    fs.set_owner(staging, 0, 0)
    try:
        for entry in entries:
            components = entry.relative_path.split("/")
            if not components or not all(_SAFE_COMPONENT_RE.fullmatch(part) for part in components):
                raise InstallerError("unsafe planned snapshot path")
            directory = staging
            for component in components[:-1]:
                directory = directory / component
                if not fs.lexists(directory):
                    fs.mkdir(directory, 0o755)
                    fs.chmod(directory, 0o755)
                    fs.set_owner(directory, 0, 0)
                _require_secure_directory(fs, directory)
            target = directory / components[-1]
            if fs.lexists(target):
                raise InstallerError("duplicate planned snapshot path")
            fs.write_new(target, entry.data, 0o644, 0, 0)
            _require_secure_regular(fs, target, MAX_SNAPSHOT_FILE_BYTES)
        _validate_snapshot_tree(fs, staging)
        return staging
    except Exception:
        try:
            if fs.lexists(staging):
                _safe_remove_tree(fs, staging, user_directory)
        except Exception:
            pass
        raise


def _install_snapshot(
    fs: FileOps,
    paths: InstallPaths,
    username: str,
    entries: Iterable[SnapshotEntry],
    rollback: RollbackStack,
) -> bool:
    user_directory = paths.snapshot_user_dir(username)
    target = paths.snapshot_root(username)
    staging = _write_snapshot_staging(fs, user_directory, entries)
    had_target = fs.lexists(target)
    backup: Optional[Path] = None
    if had_target:
        _validate_snapshot_tree(fs, target)
        backup = _unique_child(fs, user_directory, ".platform.previous-")
        fs.rename(target, backup)
    try:
        fs.rename(staging, target)
    except Exception:
        if backup is not None:
            try:
                fs.rename(backup, target)
            except Exception:
                pass
        try:
            if fs.lexists(staging):
                _safe_remove_tree(fs, staging, user_directory)
        except Exception:
            pass
        raise

    def restore_snapshot() -> None:
        if not fs.lexists(target):
            raise InstallerError("snapshot vanished before rollback")
        _safe_remove_tree(fs, target, user_directory)
        if backup is not None:
            if not fs.lexists(backup):
                raise InstallerError("previous snapshot vanished before rollback")
            fs.rename(backup, target)

    rollback.add_rollback("restore previous public snapshot", restore_snapshot)
    if backup is not None:
        rollback.add_cleanup(
            "remove replaced public snapshot",
            lambda: _safe_remove_tree(fs, backup, user_directory) if fs.lexists(backup) else None,
        )
    return True


def _dispatcher_is_managed(data: bytes) -> bool:
    return data.startswith(b"#!/") and _DISPATCHER_MARKER in data[:512]


def _config_is_managed(data: bytes) -> bool:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(parsed, dict) and parsed.get("managed_by") == restricted_ssh.MANAGED_BY


def _authorized_keys_is_managed(data: bytes) -> bool:
    return data.startswith(_AUTHORIZATION_MARKER.encode("ascii"))


def _backup_sshd_config(
    fs: FileOps,
    path: Path,
    original: bytes,
    rollback: RollbackStack,
) -> Path:
    backup = _unique_child(fs, path.parent, ".sshd_config.snowgloves-restricted-ssh-", ".bak")
    fs.write_new(backup, original, 0o600, 0, 0)

    def remove_backup() -> None:
        if not fs.lexists(backup):
            return
        current, _ = _read_managed_file(fs, backup)
        if current != original:
            raise InstallerError("sshd_config backup changed before rollback")
        fs.unlink(backup)

    rollback.add_rollback("remove failed sshd_config backup", remove_backup)
    return backup


def _run_effective_sshd(
    runner: CommandRunner,
    sshd_config: Path,
    username: str,
    source_ip: str,
) -> bytes:
    result = runner.run(
        [
            SSHD,
            "-T",
            "-f",
            str(sshd_config),
            "-C",
            "user={0},addr={1},host=localhost".format(username, source_ip),
        ],
        timeout=20,
    )
    if result.returncode != 0:
        raise InstallerError("sshd effective configuration validation failed")
    return result.stdout


def _validate_sshd_syntax(runner: CommandRunner, sshd_config: Path) -> None:
    result = runner.run([SSHD, "-t", "-f", str(sshd_config)], timeout=20)
    if result.returncode != 0:
        raise InstallerError("sshd syntax validation failed")


def validate_effective_restrictions(
    output: bytes,
    username: str,
) -> None:
    """Require sshd -T output to prove every targeted Match restriction landed."""

    try:
        lines = output.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise InstallerError("sshd effective configuration output is invalid") from exc
    actual: Dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition(" ")
        if separator:
            actual[key.lower()] = value
    command = "/usr/bin/python3 -I {0}".format(DISPATCHER_DESTINATION)
    expected = {
        "authorizedkeysfile": str(CONFIG_DIR / (username + ".authorized_keys")),
        "forcecommand": command,
        "authenticationmethods": "publickey",
        "passwordauthentication": "no",
        "kbdinteractiveauthentication": "no",
        "permittty": "no",
        "disableforwarding": "yes",
        "permituserrc": "no",
        "permituserenvironment": "no",
        "authorizedkeyscommand": "none",
        "authorizedprincipalscommand": "none",
        "authorizedprincipalsfile": "none",
        "trustedusercakeys": "none",
    }
    for key, value in expected.items():
        if actual.get(key) != value:
            raise InstallerError("sshd effective configuration lacks a required restriction")


def _validate_apply_account(
    options: InstallOptions,
    host: HostOps,
) -> Tuple[Account, Account]:
    if not host.is_darwin():
        raise InstallerError("--apply is supported only on Darwin")
    if host.effective_uid() != 0:
        raise InstallerError("--apply requires root")
    if not options.control_user:
        raise InstallerError("--apply requires --control-user for non-target SSH comparison")
    control_user = validate_username(options.control_user)
    if control_user == options.username:
        raise InstallerError("--control-user must be a different existing account")

    target = host.lookup_user(options.username)
    control = host.lookup_user(control_user)
    if target.uid == 0 or target.uid < 500:
        raise InstallerError("target must be an existing standard non-system account")
    if target.shell != "/bin/sh":
        raise InstallerError("target account shell must be exactly /bin/sh")
    if host.user_is_admin(options.username):
        raise InstallerError("target account must not be an administrator")
    if not host.group_exists(REMOTE_LOGIN_GROUP):
        raise InstallerError("Remote Login access group is absent; refusing to enable SSH for all users")
    return target, control


def _preflight_targets(
    fs: FileOps,
    paths: InstallPaths,
    plan: InstallPlan,
) -> bytes:
    _require_secure_directory(fs, paths.sshd_config.parent)
    original, _ = _read_managed_file(fs, paths.sshd_config)
    render_sshd_config(original, plan.options.username, plan.source_ip)

    existing = (
        (paths.dispatcher_destination, _dispatcher_is_managed),
        (paths.config_path(plan.options.username), _config_is_managed),
        (paths.authorized_keys_path(plan.options.username), _authorized_keys_is_managed),
    )
    for path, predicate in existing:
        if fs.lexists(path):
            data, _ = _read_managed_file(fs, path)
            if not predicate(data):
                raise InstallerError("refusing to replace unrelated existing file")

    if fs.lexists(paths.snapshot_base):
        _require_secure_directory(fs, paths.snapshot_base)
        marker = paths.snapshot_base / ".snowgloves-restricted-ssh-base"
        if not fs.lexists(marker):
            raise InstallerError("snapshot base collision is not owned by this package")
        data, _ = _read_managed_file(fs, marker)
        if data != _BASE_MARKER:
            raise InstallerError("snapshot base collision is not owned by this package")

    user_directory = paths.snapshot_user_dir(plan.options.username)
    if fs.lexists(user_directory):
        _require_secure_directory(fs, user_directory)
        marker = user_directory / ".snowgloves-restricted-ssh-owner"
        expected = _USER_MARKER_PREFIX + plan.options.username.encode("ascii") + b"\n"
        if not fs.lexists(marker):
            raise InstallerError("snapshot user directory collision is not owned by this package")
        data, _ = _read_managed_file(fs, marker)
        if data != expected:
            raise InstallerError("snapshot user directory collision is not owned by this package")
        if fs.lexists(paths.snapshot_root(plan.options.username)):
            _validate_snapshot_tree(fs, paths.snapshot_root(plan.options.username))
    return original


def prepare_install_plan(
    options: InstallOptions,
    paths: InstallPaths,
    runner: CommandRunner,
) -> InstallPlan:
    username = validate_username(options.username)
    source_ip = validate_source_ip(options.source_ip)
    public_key = read_public_key(options.public_key_file)
    commit, entries = collect_snapshot_entries(options.source_checkout, runner)
    try:
        dispatcher_data = paths.dispatcher_source.read_bytes()
    except OSError as exc:
        raise InstallerError("cannot read dispatcher source from this checkout") from exc
    if not _dispatcher_is_managed(dispatcher_data):
        raise InstallerError("dispatcher source lacks its managed ownership marker")
    if len(dispatcher_data) > MAX_MANAGED_FILE_BYTES:
        raise InstallerError("dispatcher source exceeds the managed file bound")
    root = paths.snapshot_root(username)
    return InstallPlan(
        options=InstallOptions(
            username=username,
            public_key_file=options.public_key_file,
            source_ip=source_ip,
            source_checkout=_source_checkout_path(options.source_checkout),
            apply=options.apply,
            control_user=options.control_user,
        ),
        public_key=public_key,
        source_ip=source_ip,
        commit=commit,
        entries=entries,
        config_data=build_config_data(username, root, commit),
        authorized_keys_data=build_authorized_keys_data(username, source_ip, public_key),
        dispatcher_data=dispatcher_data,
    )


def _prepare_apply_directories(
    fs: FileOps,
    paths: InstallPaths,
    username: str,
    rollback: RollbackStack,
) -> None:
    _ensure_directory(fs, paths.config_dir, rollback)

    # /usr/local is expected to exist on an administered Mac.  Creating only
    # libexec avoids recursively claiming generic system directories.
    _ensure_directory(fs, paths.dispatcher_destination.parent, rollback)

    _ensure_directory(fs, paths.snapshot_base, rollback, allow_sticky_shared_parent=True)
    _create_or_require_marker(
        fs,
        paths.snapshot_base / ".snowgloves-restricted-ssh-base",
        _BASE_MARKER,
        rollback,
    )
    user_directory = paths.snapshot_user_dir(username)
    _ensure_directory(fs, user_directory, rollback)
    _create_or_require_marker(
        fs,
        user_directory / ".snowgloves-restricted-ssh-owner",
        _USER_MARKER_PREFIX + username.encode("ascii") + b"\n",
        rollback,
    )


def _apply_plan(
    plan: InstallPlan,
    paths: InstallPaths,
    fs: FileOps,
    host: HostOps,
    runner: CommandRunner,
) -> InstallReport:
    _validate_apply_account(plan.options, host)
    original_sshd = _preflight_targets(fs, paths, plan)
    rollback = RollbackStack()
    lines: List[str] = []

    try:
        _prepare_apply_directories(fs, paths, plan.options.username, rollback)
        _install_managed_file(
            fs,
            paths.dispatcher_destination,
            plan.dispatcher_data,
            0o755,
            _dispatcher_is_managed,
            rollback,
        )
        _install_snapshot(fs, paths, plan.options.username, plan.entries, rollback)
        _install_managed_file(
            fs,
            paths.config_path(plan.options.username),
            plan.config_data,
            0o644,
            _config_is_managed,
            rollback,
        )
        _install_managed_file(
            fs,
            paths.authorized_keys_path(plan.options.username),
            plan.authorized_keys_data,
            0o644,
            _authorized_keys_is_managed,
            rollback,
        )

        control_before = _run_effective_sshd(
            runner,
            paths.sshd_config,
            plan.options.control_user or "",
            plan.source_ip,
        )
        backup = _backup_sshd_config(fs, paths.sshd_config, original_sshd, rollback)
        rendered_sshd = render_sshd_config(original_sshd, plan.options.username, plan.source_ip)
        _install_managed_file(
            fs,
            paths.sshd_config,
            rendered_sshd,
            stat.S_IMODE(_require_secure_regular(fs, paths.sshd_config).mode),
            lambda data: data == original_sshd or _match_markers(plan.options.username)[0] in data,
            rollback,
        )
        _validate_sshd_syntax(runner, paths.sshd_config)
        target_effective = _run_effective_sshd(
            runner,
            paths.sshd_config,
            plan.options.username,
            plan.source_ip,
        )
        validate_effective_restrictions(target_effective, plan.options.username)
        # The target must remain restricted even when the key's from= address does not match.
        other_effective = _run_effective_sshd(
            runner, paths.sshd_config, plan.options.username, "203.0.113.1"
        )
        validate_effective_restrictions(other_effective, plan.options.username)
        control_after = _run_effective_sshd(
            runner,
            paths.sshd_config,
            plan.options.control_user or "",
            plan.source_ip,
        )
        if control_before != control_after:
            raise InstallerError("target Match block altered the control user's effective SSH configuration")

        was_member = host.group_has_member(REMOTE_LOGIN_GROUP, plan.options.username)
        if not was_member:
            def remove_group_member() -> None:
                if host.group_has_member(REMOTE_LOGIN_GROUP, plan.options.username):
                    host.remove_group_member(REMOTE_LOGIN_GROUP, plan.options.username)

            rollback.add_rollback("remove newly added Remote Login membership", remove_group_member)
            host.add_group_member(REMOTE_LOGIN_GROUP, plan.options.username)
        if not host.group_has_member(REMOTE_LOGIN_GROUP, plan.options.username):
            raise InstallerError("Remote Login group membership did not take effect")

        cleanup_failures = rollback.commit()
        lines.extend(
            [
                "applied restricted SSH package for {0}".format(plan.options.username),
                "snapshot: {0} committed text files at {1}".format(len(plan.entries), plan.commit),
                "sshd_config backup: {0}".format(backup),
                "validated: sshd -t, target restrictions, and unchanged control-user effective config",
                "Remote Login group: {0} contains only the selected added account change".format(REMOTE_LOGIN_GROUP),
                "no sshd restart was requested",
            ]
        )
        if cleanup_failures:
            lines.append("warning: retained exact previous snapshot backup after cleanup failure")
        return InstallReport(applied=True, lines=lines)
    except Exception as exc:
        rollback_failures = rollback.rollback()
        message = "installation failed and recorded changes were rolled back"
        if rollback_failures:
            message += " (manual review required for: {0})".format(", ".join(rollback_failures))
        raise InstallerError(message) from exc


def _dry_run_report(plan: InstallPlan, paths: InstallPaths) -> InstallReport:
    username = plan.options.username
    control = plan.options.control_user or "<required-with---apply>"
    lines = [
        "dry-run: no files, accounts, SSH settings, groups, or services were changed",
        "validated input: user={0}, source-ip={1}, committed HEAD={2}".format(username, plan.source_ip, plan.commit),
        "would snapshot: {0} tracked text files / {1} bytes into {2}".format(
            len(plan.entries), plan.snapshot_bytes, paths.snapshot_root(username)
        ),
        "would install dispatcher: {0} (root:wheel 0755)".format(paths.dispatcher_destination),
        "would install config: {0} (root:wheel 0644)".format(paths.config_path(username)),
        "would install authorized key: {0} (root:wheel 0644)".format(paths.authorized_keys_path(username)),
        "would append or replace only the terminal marked Match block in {0}".format(paths.sshd_config),
        "would require on apply: Darwin, root, existing non-admin /bin/sh account, existing {0}".format(
            REMOTE_LOGIN_GROUP
        ),
        "would compare effective sshd configuration for control user: {0}".format(control),
        "would run on apply: {0} -t -f {1}".format(SSHD, paths.sshd_config),
        "would run on apply: {0} -T -f {1} -C user=<target-or-control>,addr={2},host=localhost".format(
            SSHD, paths.sshd_config, plan.source_ip
        ),
        "would add only {0} to existing {1}; no daemon restart".format(username, REMOTE_LOGIN_GROUP),
    ]
    return InstallReport(applied=False, lines=lines)


def run_install(
    options: InstallOptions,
    paths: Optional[InstallPaths] = None,
    fs: Optional[FileOps] = None,
    host: Optional[HostOps] = None,
    runner: Optional[CommandRunner] = None,
) -> InstallReport:
    """Plan a dry run or perform the narrow root-only transaction."""

    paths = paths or InstallPaths.production()
    runner = runner or CommandRunner()
    plan = prepare_install_plan(options, paths, runner)
    if not options.apply:
        return _dry_run_report(plan, paths)
    fs = fs or FileOps()
    host = host or HostOps(runner)
    return _apply_plan(plan, paths, fs, host, runner)


def _parse_args(argv: Optional[Sequence[str]] = None) -> InstallOptions:
    parser = argparse.ArgumentParser(
        description="Dry-run by default: install a forced-command, key-only macOS SSH reader."
    )
    parser.add_argument("--user", required=True, help="existing standard non-admin macOS account")
    parser.add_argument("--public-key-file", required=True, type=Path, help="one newline-free ssh-ed25519 key")
    parser.add_argument("--source-ip", required=True, help="one 100.64.0.0/10 tailnet IPv4 address")
    parser.add_argument("--source-checkout", required=True, type=Path, help="public platform Git checkout")
    parser.add_argument("--control-user", help="different existing account used for before/after sshd -T comparison")
    parser.add_argument("--apply", action="store_true", help="require root on Darwin and perform the transaction")
    parsed = parser.parse_args(argv)
    return InstallOptions(
        username=parsed.user,
        public_key_file=parsed.public_key_file,
        source_ip=parsed.source_ip,
        source_checkout=parsed.source_checkout,
        control_user=parsed.control_user,
        apply=parsed.apply,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        options = _parse_args(argv)
        report = run_install(options)
    except InstallerError as exc:
        sys.stderr.write("install_restricted_ssh.py: {0}\n".format(exc))
        return 1
    for line in report.lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

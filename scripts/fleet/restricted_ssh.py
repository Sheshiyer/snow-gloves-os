#!/usr/bin/python3
# snowgloves-restricted-ssh-dispatcher managed
"""Forced-command dispatcher for a deliberately small Snow Gloves SSH surface.

This file is installed by ``install_restricted_ssh.py`` as a root-owned script.
It intentionally has no command-line configuration: the account comes from the
effective UID and its root-owned configuration is selected from that account.
"""

from __future__ import print_function

import json
import os
import pwd
import re
import socket
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple


MANAGED_BY = "snowgloves-restricted-ssh"
CONFIG_VERSION = 1
CONFIG_DIR = Path("/etc/ssh/snowgloves")
SNAPSHOT_BASE = Path("/Users/Shared/snowgloves-readonly")

MAX_COMMAND_BYTES = 512
MAX_CONFIG_BYTES = 8192
MAX_RELATIVE_PATH_BYTES = 240
MAX_LIST_ENTRIES = 256
MAX_READ_BYTES = 64 * 1024

SCOPE = "public-platform-source"
COMPOSITE_DIAGNOSTIC = "id; hostname; pwd"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_SHELL_METACHARACTERS = set(r"""&|$`'"\\<>()[\]{}*?!~;""")


class RestrictedSSHError(Exception):
    """Raised for every denied request; main intentionally hides details."""


@dataclass(frozen=True)
class AccessConfig:
    """Validated root-owned configuration used after account selection."""

    username: str
    allowed_root: Path
    snapshot_commit: str
    scope: str


@dataclass(frozen=True)
class ParsedCommand:
    """A command that has passed the exact command grammar."""

    kind: str
    relative_parts: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PathMetadata:
    """The small lstat subset used by the trust checks."""

    mode: int
    uid: int
    gid: int
    size: int
    device: int
    inode: int


def _metadata(path: Path) -> PathMetadata:
    try:
        item = os.lstat(str(path))
    except OSError as exc:
        raise RestrictedSSHError("unavailable") from exc
    return PathMetadata(
        mode=item.st_mode,
        uid=item.st_uid,
        gid=item.st_gid,
        size=item.st_size,
        device=item.st_dev,
        inode=item.st_ino,
    )


def _is_root_owned_readonly(item: PathMetadata) -> bool:
    return item.uid == 0 and (item.mode & 0o022) == 0


def _require_secure_directory(path: Path) -> None:
    item = _metadata(path)
    if stat.S_ISLNK(item.mode) or not stat.S_ISDIR(item.mode) or not _is_root_owned_readonly(item):
        raise RestrictedSSHError("untrusted directory")


def _require_secure_regular_file(path: Path, maximum_size: Optional[int] = None) -> PathMetadata:
    item = _metadata(path)
    if stat.S_ISLNK(item.mode) or not stat.S_ISREG(item.mode) or not _is_root_owned_readonly(item):
        raise RestrictedSSHError("untrusted file")
    if maximum_size is not None and item.size > maximum_size:
        raise RestrictedSSHError("file too large")
    return item


def _open_nofollow(path: Path) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(str(path), flags)
    except OSError as exc:
        raise RestrictedSSHError("cannot open") from exc


def _read_secure_bytes(path: Path, maximum_size: int) -> bytes:
    before = _require_secure_regular_file(path, maximum_size)
    descriptor = _open_nofollow(path)
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_uid != 0
            or (after.st_mode & 0o022) != 0
            or after.st_size > maximum_size
            or after.st_dev != before.device
            or after.st_ino != before.inode
        ):
            raise RestrictedSSHError("changed during read")

        remaining = maximum_size + 1
        chunks: List[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(16384, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > maximum_size:
            raise RestrictedSSHError("file too large")
        return data
    except OSError as exc:
        raise RestrictedSSHError("cannot read") from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def effective_username() -> str:
    """Resolve the OS effective account; never accept a caller-provided username."""

    try:
        return pwd.getpwuid(os.geteuid()).pw_name
    except (KeyError, OSError) as exc:
        raise RestrictedSSHError("unknown effective account") from exc


def expected_snapshot_root(username: str, snapshot_base: Path = SNAPSHOT_BASE) -> Path:
    return snapshot_base / username / "platform"


def _parse_config_payload(
    payload: Dict[str, object],
    username: str,
    snapshot_base: Path,
) -> AccessConfig:
    required = {
        "allowed_root",
        "managed_by",
        "scope",
        "snapshot_commit",
        "user",
        "version",
    }
    if set(payload) != required:
        raise RestrictedSSHError("invalid configuration")
    if payload.get("managed_by") != MANAGED_BY or payload.get("version") != CONFIG_VERSION:
        raise RestrictedSSHError("invalid configuration")
    if payload.get("user") != username or payload.get("scope") != SCOPE:
        raise RestrictedSSHError("invalid configuration")

    expected_root = expected_snapshot_root(username, snapshot_base)
    allowed_root = payload.get("allowed_root")
    commit = payload.get("snapshot_commit")
    if not isinstance(allowed_root, str) or allowed_root != str(expected_root):
        raise RestrictedSSHError("invalid configuration")
    if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
        raise RestrictedSSHError("invalid configuration")

    return AccessConfig(
        username=username,
        allowed_root=expected_root,
        snapshot_commit=commit,
        scope=SCOPE,
    )


def load_trusted_config_for_user(
    username: str,
    config_dir: Path = CONFIG_DIR,
    snapshot_base: Path = SNAPSHOT_BASE,
) -> AccessConfig:
    """Load one trusted config after the effective OS account is already known.

    This helper exists for local unit tests and is never exposed as a command
    argument. ``load_runtime_config`` is the production entry point.
    """

    _require_secure_directory(config_dir.parent)
    _require_secure_directory(config_dir)
    config_path = config_dir / (username + ".json")
    data = _read_secure_bytes(config_path, MAX_CONFIG_BYTES)
    try:
        decoded = data.decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RestrictedSSHError("invalid configuration") from exc
    if not isinstance(payload, dict):
        raise RestrictedSSHError("invalid configuration")

    config = _parse_config_payload(payload, username, snapshot_base)
    validate_snapshot_root(config, snapshot_base)
    return config


def load_runtime_config() -> AccessConfig:
    """Production configuration loading: effective UID determines the file."""

    return load_trusted_config_for_user(effective_username())


def validate_snapshot_root(config: AccessConfig, snapshot_base: Path = SNAPSHOT_BASE) -> None:
    """Require every root component used for content access to be trustworthy."""

    if config.allowed_root != expected_snapshot_root(config.username, snapshot_base):
        raise RestrictedSSHError("unexpected snapshot root")
    _require_secure_directory(snapshot_base)
    _require_secure_directory(snapshot_base / config.username)
    _require_secure_directory(config.allowed_root)


def _has_control_or_shell_characters(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 or char in _SHELL_METACHARACTERS for char in value)


def _bounded_ascii(value: str, maximum_size: int) -> bool:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= maximum_size


def parse_relative_path(value: str) -> Tuple[str, ...]:
    """Parse a deliberately narrow, non-shell path grammar."""

    if (
        not value
        or not _bounded_ascii(value, MAX_RELATIVE_PATH_BYTES)
        or _has_control_or_shell_characters(value)
        or value.startswith("/")
        or "\\" in value
    ):
        raise RestrictedSSHError("bad path")

    parts = value.split("/")
    if len(parts) > 32:
        raise RestrictedSSHError("bad path")
    for part in parts:
        if part in ("", ".", "..") or not _PATH_COMPONENT_RE.fullmatch(part):
            raise RestrictedSSHError("bad path")
    return tuple(parts)


def parse_command(command: Optional[str]) -> ParsedCommand:
    """Allow only exact diagnostics and the three read-only command forms."""

    if not isinstance(command, str) or not command or not _bounded_ascii(command, MAX_COMMAND_BYTES):
        raise RestrictedSSHError("bad command")
    if command == COMPOSITE_DIAGNOSTIC:
        return ParsedCommand("diagnostic-composite")
    if _has_control_or_shell_characters(command):
        raise RestrictedSSHError("bad command")

    if command in ("id", "whoami", "hostname", "pwd"):
        return ParsedCommand("diagnostic-" + command)
    if command == "snowgloves-read info":
        return ParsedCommand("read-info")
    if command == "snowgloves-read list":
        return ParsedCommand("read-list")

    list_prefix = "snowgloves-read list "
    read_prefix = "snowgloves-read read "
    if command.startswith(list_prefix):
        return ParsedCommand("read-list", parse_relative_path(command[len(list_prefix) :]))
    if command.startswith(read_prefix):
        return ParsedCommand("read-file", parse_relative_path(command[len(read_prefix) :]))
    raise RestrictedSSHError("bad command")


def _checked_target(root: Path, parts: Sequence[str], want_directory: bool) -> Path:
    root_text = os.path.abspath(str(root))
    candidate = root
    _require_secure_directory(root)

    for index, part in enumerate(parts):
        candidate = candidate / part
        candidate_text = os.path.abspath(str(candidate))
        try:
            inside = os.path.commonpath((root_text, candidate_text)) == root_text
        except ValueError as exc:
            raise RestrictedSSHError("outside root") from exc
        if not inside:
            raise RestrictedSSHError("outside root")
        item = _metadata(candidate)
        final = index == len(parts) - 1
        if stat.S_ISLNK(item.mode) or not _is_root_owned_readonly(item):
            raise RestrictedSSHError("untrusted snapshot path")
        if final:
            if want_directory and not stat.S_ISDIR(item.mode):
                raise RestrictedSSHError("not a directory")
            if not want_directory and not stat.S_ISREG(item.mode):
                raise RestrictedSSHError("not a regular file")
        elif not stat.S_ISDIR(item.mode):
            raise RestrictedSSHError("not a directory")
    return candidate


def read_snapshot_text(root: Path, parts: Sequence[str]) -> str:
    """Read one already-authorized snapshot path, bounded and nofollow."""

    target = _checked_target(root, parts, want_directory=False)
    data = _read_secure_bytes(target, MAX_READ_BYTES)
    if b"\x00" in data:
        raise RestrictedSSHError("binary file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RestrictedSSHError("binary file") from exc
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise RestrictedSSHError("binary file")
    return text


def list_snapshot(root: Path, parts: Sequence[str]) -> List[str]:
    """List a single trusted directory, rejecting unexpected filesystem types."""

    target = _checked_target(root, parts, want_directory=True)
    results: List[str] = []
    seen_entries = 0
    try:
        with os.scandir(str(target)) as entries:
            for entry in entries:
                # Count every directory entry, including malformed ones, so an
                # attacker cannot bypass the response bound with junk names.
                seen_entries += 1
                if seen_entries > MAX_LIST_ENTRIES:
                    raise RestrictedSSHError("too many entries")
                if not _PATH_COMPONENT_RE.fullmatch(entry.name):
                    raise RestrictedSSHError("unsafe entry")
                child = target / entry.name
                item = _metadata(child)
                if stat.S_ISLNK(item.mode) or not _is_root_owned_readonly(item):
                    raise RestrictedSSHError("unsafe entry")
                if stat.S_ISDIR(item.mode):
                    results.append(entry.name + "/")
                elif stat.S_ISREG(item.mode):
                    results.append(entry.name)
                else:
                    raise RestrictedSSHError("unsafe entry")
    except OSError as exc:
        raise RestrictedSSHError("cannot list") from exc
    return sorted(results)


def _fixed_id() -> str:
    """Run only the fixed system id program with a deliberately minimal env."""

    try:
        completed = subprocess.run(
            ["/usr/bin/id"],
            check=False,
            close_fds=True,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RestrictedSSHError("diagnostic unavailable") from exc
    if completed.returncode != 0:
        raise RestrictedSSHError("diagnostic unavailable")
    try:
        return completed.stdout.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise RestrictedSSHError("diagnostic unavailable") from exc


@dataclass(frozen=True)
class DiagnosticProviders:
    """Injectable pure seams for tests; production uses fixed local providers."""

    id_output: Callable[[], str]
    hostname: Callable[[], str]
    current_directory: Callable[[], str]


def production_diagnostic_providers() -> DiagnosticProviders:
    return DiagnosticProviders(
        id_output=_fixed_id,
        hostname=socket.gethostname,
        current_directory=os.getcwd,
    )


def _diagnostic_output(
    kind: str,
    username: str,
    providers: DiagnosticProviders,
) -> str:
    if kind == "id":
        output = providers.id_output()
        return output if output.endswith("\n") else output + "\n"
    if kind == "whoami":
        return username + "\n"
    if kind == "hostname":
        return providers.hostname() + "\n"
    if kind == "pwd":
        return providers.current_directory() + "\n"
    raise RestrictedSSHError("unknown diagnostic")


def dispatch_trusted_command(
    command: Optional[str],
    config: AccessConfig,
    providers: Optional[DiagnosticProviders] = None,
) -> str:
    """Dispatch after the caller has established config and snapshot trust.

    ``main`` obtains ``config`` only through ``load_runtime_config``. Tests use
    this narrow helper with temporary snapshots to exercise command behavior
    without pretending their fixture files are root-owned.
    """

    parsed = parse_command(command)
    providers = providers or production_diagnostic_providers()

    if parsed.kind == "diagnostic-composite":
        return (
            _diagnostic_output("id", config.username, providers)
            + _diagnostic_output("hostname", config.username, providers)
            + _diagnostic_output("pwd", config.username, providers)
        )
    if parsed.kind.startswith("diagnostic-"):
        return _diagnostic_output(parsed.kind[len("diagnostic-") :], config.username, providers)
    if parsed.kind == "read-info":
        return (
            "user={0}\n"
            "host={1}\n"
            "snapshot_commit={2}\n"
            "scope={3}\n"
        ).format(config.username, providers.hostname(), config.snapshot_commit, config.scope)
    if parsed.kind == "read-list":
        entries = list_snapshot(config.allowed_root, parsed.relative_parts)
        return "".join(item + "\n" for item in entries)
    if parsed.kind == "read-file":
        return read_snapshot_text(config.allowed_root, parsed.relative_parts)
    raise RestrictedSSHError("unknown command")


def dispatch_command(command: Optional[str], config: AccessConfig) -> str:
    """Production dispatch with a fresh snapshot-root trust check."""

    validate_snapshot_root(config)
    return dispatch_trusted_command(command, config)


def main() -> int:
    try:
        config = load_runtime_config()
        output = dispatch_command(os.environ.get("SSH_ORIGINAL_COMMAND"), config)
    except RestrictedSSHError:
        sys.stderr.write("restricted SSH command denied\n")
        return 1
    except Exception:
        # Never turn a parsing or filesystem edge into an informative remote oracle.
        sys.stderr.write("restricted SSH command denied\n")
        return 1
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

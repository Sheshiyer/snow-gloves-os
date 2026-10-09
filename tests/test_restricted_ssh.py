"""Focused safety tests for the root-installed restricted SSH package.

The tests use temporary files plus explicit fake command/filesystem boundaries;
they never invoke sshd, dseditgroup, dsmemberutil, sudo, an SSH client, or a
real macOS account/group.
"""

from __future__ import annotations

import base64
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fleet import install_restricted_ssh as installer  # noqa: E402
from fleet import restricted_ssh as dispatcher  # noqa: E402


USER = "sg-observer"
CONTROL = "sg-control"
SOURCE_IP = "100.64.12.34"
COMMIT = "a" * 40


def synthetic_public_key(comment: str = "observer@example.invalid") -> str:
    wire = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + (b"\x01" * 32)
    return "ssh-ed25519 {0} {1}".format(base64.b64encode(wire).decode("ascii"), comment)


class RootOwnedFixture:
    """Make a temporary tree look root-owned to dispatcher trust checks only."""

    def __init__(self, monkeypatch):
        original_metadata = dispatcher._metadata
        original_fstat = dispatcher.os.fstat

        def metadata(path: Path) -> dispatcher.PathMetadata:
            actual = original_metadata(path)
            return dispatcher.PathMetadata(
                mode=actual.mode,
                uid=0,
                gid=0,
                size=actual.size,
                device=actual.device,
                inode=actual.inode,
            )

        def fstat(descriptor: int):
            actual = original_fstat(descriptor)
            return SimpleNamespace(
                st_mode=actual.st_mode,
                st_uid=0,
                st_gid=0,
                st_size=actual.st_size,
                st_dev=actual.st_dev,
                st_ino=actual.st_ino,
            )

        monkeypatch.setattr(dispatcher, "_metadata", metadata)
        monkeypatch.setattr(dispatcher.os, "fstat", fstat)


@pytest.fixture
def trusted_snapshot(tmp_path, monkeypatch):
    RootOwnedFixture(monkeypatch)
    base = tmp_path / "readonly"
    root = base / USER / "platform"
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text("public source\n", encoding="utf-8")
    (root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    return base, root


def access_config(root: Path) -> dispatcher.AccessConfig:
    return dispatcher.AccessConfig(
        username=USER,
        allowed_root=root,
        snapshot_commit=COMMIT,
        scope=dispatcher.SCOPE,
    )


def fake_providers() -> dispatcher.DiagnosticProviders:
    return dispatcher.DiagnosticProviders(
        id_output=lambda: "uid=501(sg-observer) gid=20(staff)\n",
        hostname=lambda: "synthetic-mac.example.invalid",
        current_directory=lambda: "/",
    )


def test_dispatcher_allows_exact_diagnostics_and_login_canary(trusted_snapshot):
    _, root = trusted_snapshot
    config = access_config(root)

    assert dispatcher.parse_command("id").kind == "diagnostic-id"
    assert dispatcher.parse_command("whoami").kind == "diagnostic-whoami"
    assert dispatcher.parse_command("hostname").kind == "diagnostic-hostname"
    assert dispatcher.parse_command("pwd").kind == "diagnostic-pwd"
    assert dispatcher.parse_command("id; hostname; pwd").kind == "diagnostic-composite"
    assert dispatcher.dispatch_trusted_command("whoami", config, fake_providers()) == USER + "\n"
    assert dispatcher.dispatch_trusted_command("id; hostname; pwd", config, fake_providers()) == (
        "uid=501(sg-observer) gid=20(staff)\n"
        "synthetic-mac.example.invalid\n"
        "/\n"
    )


@pytest.mark.parametrize(
    "command",
    [
        "",
        "id; hostname; pwd; id",
        "id ; hostname; pwd",
        "echo hello",
        "snowgloves-read read docs/guide.md;id",
        "snowgloves-read list docs\tprivate",
        "snowgloves-read read docs/guide.md | cat",
        "internal-sftp",
    ],
)
def test_dispatcher_rejects_shell_forms_and_unsupported_commands(command):
    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.parse_command(command)


@pytest.mark.parametrize(
    "value",
    [
        "/etc/passwd",
        "../README.md",
        "docs/../README.md",
        "docs//guide.md",
        "docs/\x01guide.md",
        "docs/guide.md\nid",
        "docs/guide.md$HOME",
        "docs/" + ("a" * (dispatcher.MAX_RELATIVE_PATH_BYTES + 1)),
    ],
)
def test_dispatcher_rejects_traversal_controls_and_oversize_paths(value):
    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.parse_relative_path(value)


def test_dispatcher_info_and_read_only_source_commands(trusted_snapshot):
    _, root = trusted_snapshot
    config = access_config(root)

    info = dispatcher.dispatch_trusted_command("snowgloves-read info", config, fake_providers())
    assert info.splitlines() == [
        "user=sg-observer",
        "host=synthetic-mac.example.invalid",
        "snapshot_commit=" + COMMIT,
        "scope=public-platform-source",
    ]
    assert dispatcher.dispatch_trusted_command("snowgloves-read list", config, fake_providers()) == "README.md\ndocs/\n"
    assert dispatcher.dispatch_trusted_command("snowgloves-read list docs", config, fake_providers()) == "guide.md\n"
    assert dispatcher.dispatch_trusted_command("snowgloves-read read docs/guide.md", config, fake_providers()) == "guide\n"


def test_dispatcher_rejects_symlink_components_and_binary_or_oversize_files(trusted_snapshot, tmp_path):
    _, root = trusted_snapshot
    (root / "binary.md").write_bytes(b"plain\x00binary")
    (root / "large.md").write_bytes(b"x" * (dispatcher.MAX_READ_BYTES + 1))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("not reachable\n", encoding="utf-8")
    os.symlink(outside, root / "linked")
    os.symlink(outside / "secret.md", root / "file-link.md")

    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.read_snapshot_text(root, ("binary.md",))
    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.read_snapshot_text(root, ("large.md",))
    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.read_snapshot_text(root, ("linked", "secret.md"))
    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.read_snapshot_text(root, ("file-link.md",))


def test_dispatcher_bounds_directory_listing(trusted_snapshot):
    _, root = trusted_snapshot
    many = root / "many"
    many.mkdir()
    for index in range(dispatcher.MAX_LIST_ENTRIES + 1):
        (many / "entry{0:03d}.md".format(index)).write_text("x\n", encoding="utf-8")

    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.list_snapshot(root, ("many",))


def test_dispatcher_loads_only_expected_root_owned_effective_user_config(trusted_snapshot, tmp_path):
    base, root = trusted_snapshot
    config_dir = tmp_path / "etc" / "ssh" / "snowgloves"
    config_dir.mkdir(parents=True)
    config_path = config_dir / (USER + ".json")
    config_path.write_bytes(installer.build_config_data(USER, root, COMMIT))

    loaded = dispatcher.load_trusted_config_for_user(USER, config_dir=config_dir, snapshot_base=base)
    assert loaded == access_config(root)

    config_path.write_bytes(installer.build_config_data("other-user", root, COMMIT))
    with pytest.raises(dispatcher.RestrictedSSHError):
        dispatcher.load_trusted_config_for_user(USER, config_dir=config_dir, snapshot_base=base)


def test_key_ip_and_config_generation_are_narrow(tmp_path):
    key = synthetic_public_key()
    assert installer.validate_public_key_bytes(key.encode("ascii")) == key
    assert installer.validate_source_ip(SOURCE_IP) == SOURCE_IP
    assert installer.validate_username(USER) == USER

    for invalid in (
        key + "\n",
        'from="100.64.0.1" ' + key,
        key + " extra words",
        key.replace("observer@example.invalid", "comment with spaces"),
    ):
        with pytest.raises(installer.InstallerError):
            installer.validate_public_key_bytes(invalid.encode("ascii"))
    for invalid_ip in ("100.128.0.1", "100.64.0.1/32", "fd7a:115c:a1e0::1"):
        with pytest.raises(installer.InstallerError):
            installer.validate_source_ip(invalid_ip)
    for invalid_user in ("root", "Admin", "sg observer", "../sg"):
        with pytest.raises(installer.InstallerError):
            installer.validate_username(invalid_user)

    snapshot = tmp_path / "readonly" / USER / "platform"
    config = json_loads(installer.build_config_data(USER, snapshot, COMMIT))
    assert config == {
        "allowed_root": str(snapshot),
        "managed_by": "snowgloves-restricted-ssh",
        "scope": "public-platform-source",
        "snapshot_commit": COMMIT,
        "user": USER,
        "version": 1,
    }
    authorized = installer.build_authorized_keys_data(USER, SOURCE_IP, key).decode("ascii")
    assert authorized.startswith("# snowgloves-restricted-ssh managed key for sg-observer\n")
    assert 'restrict,from="100.64.12.34",command="/usr/bin/python3 -I /usr/local/libexec/snowgloves-restricted-ssh.py"' in authorized


def json_loads(data: bytes):
    import json

    return json.loads(data.decode("utf-8"))


def test_snapshot_selector_excludes_private_and_non_text_paths():
    assert installer._is_selected_snapshot_path("docs/fleet-restricted-ssh.md")
    assert installer._is_selected_snapshot_path("apps/infra-block/src/main.ts")
    for path in (
        "ISA.md",
        "docs/.private/notes.md",
        "tenants/acme/brief.md",
        "scripts/keys/example.py",
        "apps/onboarding/src/main.ts",
        "docs/image.png",
    ):
        assert not installer._is_selected_snapshot_path(path)


def test_sshd_match_block_stays_late_and_preserves_original_bytes():
    original = b"# existing global option\nInclude /etc/ssh/sshd_config.d/*\n"
    rendered = installer.render_sshd_config(original, USER, SOURCE_IP)

    assert rendered.startswith(original)
    assert rendered.endswith(b"# END snowgloves-restricted-ssh sg-observer\n")
    assert b"Match User sg-observer\n" in rendered
    assert b"    ForceCommand /usr/bin/python3 -I /usr/local/libexec/snowgloves-restricted-ssh.py\n" in rendered
    assert b"    DisableForwarding yes\n" in rendered
    assert installer.render_sshd_config(rendered, USER, SOURCE_IP) == rendered

    unsafe = rendered + b"PasswordAuthentication yes\n"
    with pytest.raises(installer.InstallerError):
        installer.render_sshd_config(unsafe, USER, SOURCE_IP)


class FakeRunner(installer.CommandRunner):
    """No command is executed; only exact argv is observed and canned."""

    def __init__(self, fail_sshd_test: bool = False):
        self.calls = []
        self.fail_sshd_test = fail_sshd_test
        self.blob = b"public source\n"
        self.object_id = "b" * 40

    def run(self, args, cwd=None, timeout=30.0):
        args = tuple(args)
        self.calls.append(args)
        if args[0] == installer.GIT:
            if "rev-parse" in args:
                return installer.CommandResult(0, (COMMIT + "\n").encode("ascii"))
            if "ls-tree" in args:
                tree = "100644 blob {0}\tREADME.md\0".format(self.object_id).encode("ascii")
                return installer.CommandResult(0, tree)
            if "cat-file" in args and "-s" in args:
                return installer.CommandResult(0, str(len(self.blob)).encode("ascii") + b"\n")
            if "cat-file" in args and "blob" in args:
                return installer.CommandResult(0, self.blob)
            raise AssertionError("unexpected Git argv: {0!r}".format(args))
        if args[0] == installer.SSHD and "-t" in args:
            return installer.CommandResult(1 if self.fail_sshd_test else 0)
        if args[0] == installer.SSHD and "-T" in args:
            return installer.CommandResult(0, b"control-effective-configuration\n")
        raise AssertionError("unexpected command argv: {0!r}".format(args))


class RootedTempFileOps(installer.FileOps):
    """Temporary filesystem with fake root ownership, used only for installer tests."""

    def metadata(self, path: Path) -> installer.FileMetadata:
        actual = super().metadata(path)
        return installer.FileMetadata(
            mode=actual.mode,
            uid=0,
            gid=0,
            size=actual.size,
            device=actual.device,
            inode=actual.inode,
        )

    def set_owner(self, path: Path, uid: int, gid: int) -> None:
        return None


class FakeHost:
    def __init__(self):
        self.members = set()
        self.add_calls = []
        self.remove_calls = []

    def is_darwin(self):
        return True

    def effective_uid(self):
        return 0

    def lookup_user(self, username):
        if username == USER:
            return installer.Account(USER, 501, 20, "/bin/sh")
        if username == CONTROL:
            return installer.Account(CONTROL, 502, 20, "/bin/sh")
        raise installer.InstallerError("unknown fake account")

    def user_is_admin(self, username):
        return False

    def group_exists(self, group_name):
        return group_name == installer.REMOTE_LOGIN_GROUP

    def group_has_member(self, group_name, username):
        return (group_name, username) in self.members

    def add_group_member(self, group_name, username):
        self.add_calls.append((group_name, username))
        self.members.add((group_name, username))

    def remove_group_member(self, group_name, username):
        self.remove_calls.append((group_name, username))
        self.members.discard((group_name, username))


def test_installer_dry_run_does_not_touch_target_files(tmp_path):
    key_path = tmp_path / "observer.pub"
    key_path.write_text(synthetic_public_key(), encoding="ascii")
    source = tmp_path / "source"
    source.mkdir()
    machine = tmp_path / "machine"
    paths = installer.InstallPaths(
        dispatcher_source=ROOT / "scripts" / "fleet" / "restricted_ssh.py",
        dispatcher_destination=machine / "usr" / "local" / "libexec" / "snowgloves-restricted-ssh.py",
        sshd_config=machine / "etc" / "ssh" / "sshd_config",
        config_dir=machine / "etc" / "ssh" / "snowgloves",
        snapshot_base=machine / "Users" / "Shared" / "snowgloves-readonly",
    )
    before = set(tmp_path.rglob("*"))
    report = installer.run_install(
        installer.InstallOptions(USER, key_path, SOURCE_IP, source),
        paths=paths,
        runner=FakeRunner(),
    )

    assert not report.applied
    assert any(line.startswith("dry-run:") for line in report.lines)
    assert set(tmp_path.rglob("*")) == before
    assert not machine.exists()


def test_installer_rolls_back_owned_files_after_fake_sshd_validation_failure(tmp_path):
    key_path = tmp_path / "observer.pub"
    key_path.write_text(synthetic_public_key(), encoding="ascii")
    source = tmp_path / "source"
    source.mkdir()
    machine = tmp_path / "machine"
    ssh_directory = machine / "etc" / "ssh"
    ssh_directory.mkdir(parents=True)
    original_sshd = b"# original bytes stay intact\n"
    (ssh_directory / "sshd_config").write_bytes(original_sshd)
    local = machine / "usr" / "local"
    local.mkdir(parents=True)
    shared = machine / "Users" / "Shared"
    shared.mkdir(parents=True)
    os.chmod(shared, stat.S_ISVTX | 0o777)

    paths = installer.InstallPaths(
        dispatcher_source=ROOT / "scripts" / "fleet" / "restricted_ssh.py",
        dispatcher_destination=local / "libexec" / "snowgloves-restricted-ssh.py",
        sshd_config=ssh_directory / "sshd_config",
        config_dir=ssh_directory / "snowgloves",
        snapshot_base=shared / "snowgloves-readonly",
    )
    runner = FakeRunner(fail_sshd_test=True)
    host = FakeHost()
    options = installer.InstallOptions(
        USER,
        key_path,
        SOURCE_IP,
        source,
        apply=True,
        control_user=CONTROL,
    )

    with pytest.raises(installer.InstallerError, match="rolled back"):
        installer.run_install(
            options,
            paths=paths,
            fs=RootedTempFileOps(),
            host=host,
            runner=runner,
        )

    assert paths.sshd_config.read_bytes() == original_sshd
    assert not paths.dispatcher_destination.exists()
    assert not paths.config_dir.exists()
    assert not paths.snapshot_base.exists()
    assert host.add_calls == []
    assert any(call[0] == installer.SSHD and "-t" in call for call in runner.calls)


def effective_policy():
    return ("authorizedkeysfile /etc/ssh/snowgloves/sg-observer.authorized_keys\n"
            "forcecommand /usr/bin/python3 -I /usr/local/libexec/snowgloves-restricted-ssh.py\n"
            "authenticationmethods publickey\npasswordauthentication no\n"
            "kbdinteractiveauthentication no\npermittty no\ndisableforwarding yes\n"
            "permituserrc no\npermituserenvironment no\nauthorizedkeyscommand none\n"
            "authorizedprincipalscommand none\nauthorizedprincipalsfile none\n"
            "trustedusercakeys none\n").encode()


def test_user_policy_applies_at_all_addresses_and_refuses_alternate_key_authorities():
    block = installer.build_match_block(USER, SOURCE_IP)
    assert b"Match User sg-observer\n" in block and b" Address " not in block
    assert b"PermitUserEnvironment" not in block
    installer.validate_effective_restrictions(effective_policy(), USER)
    for key in (b"authorizedkeyscommand", b"trustedusercakeys", b"permituserenvironment"):
        unsafe = effective_policy().replace(key + b" none", key + b" /unsafe")
        if key == b"permituserenvironment":
            unsafe = effective_policy().replace(key + b" no", key + b" yes")
        with pytest.raises(installer.InstallerError):
            installer.validate_effective_restrictions(unsafe, USER)


@pytest.mark.parametrize("message,member", [(b"user is a member of the group\n", True),
                                           (b"user is not a member of the group\n", False)])
def test_membership_uses_successful_query_output(message, member):
    runner = SimpleNamespace(run=lambda *args, **kwargs: installer.CommandResult(0, message))
    assert installer.HostOps(runner)._membership(USER, "admin") is member


def test_underscore_source_files_and_normal_public_file_newline(trusted_snapshot, tmp_path):
    _, root = trusted_snapshot
    (root / "docs" / "__init__.py").write_text("# package\n")
    assert installer._is_selected_snapshot_path("scripts/lib/__init__.py")
    assert "__init__.py" in dispatcher.dispatch_trusted_command("snowgloves-read list docs", access_config(root))
    assert dispatcher.dispatch_trusted_command("snowgloves-read read docs/__init__.py", access_config(root)) == "# package\n"
    key = tmp_path / "normal.pub"
    key.write_text(synthetic_public_key() + "\n")
    assert installer.read_public_key(key) == synthetic_public_key()
    key.write_text(synthetic_public_key() + "\n\n")
    with pytest.raises(installer.InstallerError):
        installer.read_public_key(key)


def test_apply_success_is_readable_idempotent_and_checks_other_address(tmp_path):
    machine = tmp_path / "machine"
    sshdir = machine / "etc" / "ssh"
    sshdir.mkdir(parents=True)
    (sshdir / "sshd_config").write_bytes(b"# founder configuration\n")
    local = machine / "usr" / "local"
    local.mkdir(parents=True)
    shared = machine / "Users" / "Shared"
    shared.mkdir(parents=True)
    shared.chmod(0o1777)
    key = tmp_path / "observer.pub"
    key.write_text(synthetic_public_key())
    source = tmp_path / "source"
    source.mkdir()
    paths = installer.InstallPaths(ROOT / "scripts/fleet/restricted_ssh.py",
        local / "libexec/snowgloves-restricted-ssh.py", sshdir / "sshd_config",
        sshdir / "snowgloves", shared / "snowgloves-readonly")

    class SuccessfulRunner(FakeRunner):
        def run(self, args, **kwargs):
            if args[0] == installer.SSHD and "-T" in args:
                self.calls.append(tuple(args))
                return installer.CommandResult(0, effective_policy() if "user=" + USER + "," in args[-1] else b"founder unchanged\n")
            return super().run(args, **kwargs)

    runner, host = SuccessfulRunner(), FakeHost()
    options = installer.InstallOptions(USER, key, SOURCE_IP, source, apply=True, control_user=CONTROL)
    for _ in range(2):
        assert installer.run_install(options, paths=paths, fs=RootedTempFileOps(), host=host, runner=runner).applied
        assert stat.S_IMODE(paths.config_path(USER).stat().st_mode) == 0o644
        assert paths.sshd_config.read_bytes().count(b"Match User ") == 1
    assert len(host.add_calls) == 1
    assert any("addr=203.0.113.1" in arg for call in runner.calls for arg in call)


@pytest.mark.parametrize("path", ["scripts/_runtime/session.json", "docs/credentials.json", "scripts/secrets.yaml"])
def test_private_runtime_and_credential_named_files_are_excluded(path):
    assert not installer._is_selected_snapshot_path(path)

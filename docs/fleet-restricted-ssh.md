# Restricted SSH for a fleet client

This package gives one existing standard macOS account fixed diagnostics and bounded reads of a protected public platform snapshot. It does not provide a general shell, project task credentials, model access or private operations data. The default invocation is a dry run.

## Administrator preparation

Create a dedicated standard account locally on the target Mac. Do not put passwords into command arguments or messages. Use the native interactive prompt:

```sh
sudo /usr/sbin/sysadminctl -addUser sg-observer -fullName 'Fleet observer' -shell /bin/sh -password -
```

The installer refuses an administrator, system account, other shell, absent Remote Login access group, untrusted install paths, or an apply without root and a distinct existing control account. Back up/review the source first. Keep the two Python scripts together in a founder-controlled staging directory. A public key file may have one final newline; use a bare Ed25519 key with at most one harmless comment token.

```sh
/usr/bin/python3 -B -E -s install_restricted_ssh.py --user sg-observer --public-key-file observer.pub --source-ip 100.64.12.34 --source-checkout /path/to/public-platform --control-user operator
```

After reviewing the dry run, repeat with sudo and --apply. Administrator authentication happens only on that Mac. No passwords are accepted by this installer.

## Enforced scope

The root-owned forced dispatcher uses /usr/bin/python3 -I. Its nonsecret metadata config is root-owned0644 so the target can read it. The account is restricted at every source address; its sole central key carries restrict and from= for the selected tailnet IPv4. Effective checks refuse alternate key commands, CA/principal sources or enabled user environment processing. Global SSH policy is preserved. The marked user block is appended at the end of sshd_config; syntax, target policy at approved and other addresses, and unchanged control-user policy are checked before success. No daemon restart is requested. Failure rolls back tracked files and newly added Remote Login membership. Rerunning the package safely replaces its own marked snapshot/configuration and retains an SSH configuration backup.

The snapshot contains only selected committed regular text blobs from public platform paths. Dot paths, private instance/planning/runtime paths, symlinks, Git internals, binaries and credential-like content are excluded. Some public source files may therefore be omitted. Reads are capped at64KiB; directory listings and command/path lengths are bounded. The snapshot is outside founder/private home data and writable only by root.

Allowed commands are id, whoami, hostname, pwd, the exact sequence id; hostname; pwd, snowgloves-read info, snowgloves-read list with an optional relative directory, and snowgloves-read read with one relative file. Shell syntax, arbitrary executables, traversal, symlinks, writes, interactive terminals, forwarding and file-transfer subsystems are denied.

## Client/device acceptance

Preserve the dedicated client SSH key and host pin. Use AddressFamily inet or ssh -4 because the central key is scoped to an IPv4 source. Verify the host fingerprint independently. From the authorized laptop, prove key login, diagnostics, info/list/read, then denied shell/write/traversal and attempted forwarded channels. A local port listener alone is not a forwarding proof. Confirm existing operator SSH still works. Source/unit tests do not substitute for these actual-device checks.

Keep the separate Hermes profile parked without a model during transport verification if desired. SSH readiness and actual Hermes/model readiness are distinct. Do not borrow the operator account or share task/gateway credentials. Fleet MCP and project task operations require separate requester/project authorization; they are outside this diagnostics/public-source package.

# 01. Apple Account and users: the first hour of each mini

Do this on each mini, at the keyboard, before Tailscale and before any software from
`docs/MAC-MINI-SETUP.md`. Order matters: FileVault and the operator user shape everything after.

## The one company Apple Account

One Apple Account, owned by Thoughtseed, is signed in on all three minis. It is used for:

| Purpose | Where |
|---|---|
| Mac App Store: Xcode, the Apple Remote Desktop admin app | the founder's Mac installs Remote Desktop; minis need only the App Store sign-in |
| Software updates and Find My | every mini |
| Nothing else | no mail, no personal data, no iCloud document sync |

Two-factor authentication is on; the trusted phone number is the company phone, not a personal
one. Recovery contact and the account password live in the company password manager.

iCloud: turn **everything off except Find My Mac**. In particular off: iCloud Drive, Desktop &
Documents, Photos, Mail, Contacts, Calendars, Notes, Passwords & Keychain. The onboarding plan is
explicit: "Do not synchronize runtime directories, live databases, OAuth caches, or dotenv secrets
through iCloud." A shared Keychain across three machines would do exactly that.

The Apple Account proves nothing about brands or permissions: "A trusted mini or shared Apple
account is not an organization principal" (`specs/005-node-bootstrap/spec.md`).

## Checklist

Tick in order. `<wing>` is `marketing`, `design` or `coding`.

| # | Step | How | Done |
|---|---|---|---|
| 1 | Setup Assistant: create the first user as `sg-admin` (admin) | at the keyboard; password from the password manager | [ ] |
| 2 | Sign in the company Apple Account; approve the two-factor prompt on the company phone | System Settings > Apple Account | [ ] |
| 3 | iCloud: all off except Find My Mac | System Settings > Apple Account > iCloud | [ ] |
| 4 | Computer name = `fleet.yaml` hostname (`<wing>-mac`) | `remote_access.sh` step 1, or General > About > Name | [ ] |
| 5 | Create `sg-<wing>` as a **standard** user (the daily operator) | `remote_access.sh` step 2, or Users & Groups | [ ] |
| 6 | FileVault **on**; recovery key into the company password manager, never into git or a note | Privacy & Security > FileVault | [ ] |
| 7 | Automatic login **off** (FileVault forces this; confirm) | Users & Groups > Automatic login | [ ] |
| 8 | Energy: never sleep, start after power failure, auto-restart on freeze, wake for network | `remote_access.sh` step 5 (`pmset`), or Energy | [ ] |
| 9 | Software Update: security responses and system files automatic; macOS upgrades manual | General > Software Update > Automatic Updates | [ ] |
| 10 | Log out of `sg-admin`, log in as `sg-<wing>`; everything after this page happens there | login window | [ ] |

The script that prints steps 4, 5 and 8 as commands (dry-run; `--apply` to run on the mini):

```bash
bash scripts/fleet/remote_access.sh --wing <wing>
```

Why security responses only: the Coding Mac is the gateway. A full macOS upgrade that reboots it
unannounced takes the fleet's model routing down (see [07-OPERATIONS.md](07-OPERATIONS.md)).
Upgrade it on purpose, in a window, with `sudo fdesetup authrestart` so it comes back without
someone typing the FileVault password.

## Users

| User | Kind | Used for |
|---|---|---|
| `sg-admin` | admin | installs, `sudo`, `remote_access.sh --apply`, recovery. Never for daily work. |
| `sg-<wing>` | standard | everything else: runtimes, tenants, Screen Sharing sessions, SSH, the gateway key in its Keychain |

One operator user per wing is shared by the people on that wing. That is a deliberate trade-off:
macOS logs show `sg-marketing`, not which person was at the keyboard. The mitigation (Tailscale
identity per person, `SNOWGLOVES_ACTOR`, per-person SSH keys) is in
[06-TEAM-ACCESS.md](06-TEAM-ACCESS.md). The alternative, one macOS user per person per mini, costs
a login, a Keychain and a rendered runtime per person per machine, and is the upgrade path below.

## FileVault and an always-on machine

FileVault protects a stolen mini. It also means that after a power loss the Mac stops at the
pre-boot unlock screen and nothing (Tailscale, OmniRoute, Screen Sharing) runs until someone in
the office types a password. For the Coding Mac: put it on a UPS, use `sudo fdesetup authrestart`
for planned reboots, and accept that an unplanned power loss needs a person in Paris. This is
recorded as a decision in [DECISIONS.md](DECISIONS.md).

## Later: Apple Business Manager, Managed Apple Accounts, MDM

Not required now, and explicitly not part of the pilot. It needs a D-U-N-S number for Thoughtseed,
enrollment, and an MDM product. When the fleet grows past three machines or past a handful of
people it would add:

- Managed Apple Accounts per person instead of one shared company account.
- Automated Device Enrollment: a new mini configures itself out of the box.
- FileVault recovery key escrow and remote lock or wipe from the console.
- Configuration profiles for the settings on this page, enforced instead of ticked.
- App Store volume licences assigned to devices, not to the shared account.

Until then this checklist plus `remote_access.sh` is the whole of device management.

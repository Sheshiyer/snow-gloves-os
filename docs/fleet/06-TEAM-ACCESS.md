# 06. Team access: seats, onboarding, offboarding, audit

Step 8 of the [README](README.md). People get seats; machines get wings; brands get tenants.
Nothing in this page grants brand permissions: those come from the tenant's `enabled.yaml` and
approvals, and "a trusted mini or shared Apple account is not an organization principal"
(`specs/005-node-bootstrap/spec.md`).

## What a seat is

A seat on a wing is four things, each revocable on its own:

| Part | Identity it carries | Where it lives |
|---|---|---|
| Tailscale login | the person (their own account, device tagged `tag:team`) | Tailscale admin console |
| Wing operator user | the wing (`sg-marketing`, `sg-design`, `sg-coding`), shared | the mini |
| Remote Management privilege | the operator user, inherited | the mini (set by `remote_access.sh`) |
| Scoped gateway key | one key per machine the person works from | Keychain on that machine, named `snowgloves-gateway-<wing>` |

The founder's seat adds Apple Remote Desktop and `sg-admin`. Nobody else uses `sg-admin` day to day.

## Onboarding checklist

| # | Step | Who | How |
|---|---|---|---|
| 1 | Add the person to the tailnet; tag their Mac `tag:team` | founder | admin console invite; tag on first connect |
| 2 | Share the wing operator password | founder | company password manager share, never chat or email |
| 3 | Add their SSH public key to the wing | founder or the person over Screen Sharing | see below |
| 4 | Issue a gateway key for their machine | founder | `04-GATEWAY.md`; stored under `keychain:snowgloves-gateway-<wing>` |
| 5 | Tell them the one command | founder | `bash scripts/fleet/connect.sh <wing>` (add `ssh` for a shell) |
| 6 | Tell them to set their actor name | founder | `export SNOWGLOVES_ACTOR="<their name>"` in their shell on the wing (below) |

Step 3, on the wing as the operator user:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "<their public key> <their name>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Keep the comment at the end of each key line as the person's name; it is the only place the
shared user's SSH setup records who a key belongs to.

## Offboarding checklist

Do all four; each closes a different door.

| # | Step | How |
|---|---|---|
| 1 | Remove their device(s) from the tailnet | admin console > Machines > remove; this alone cuts every path to every wing |
| 2 | Rotate the operator password on every wing they used | `sudo sysadminctl -resetPasswordFor sg-<wing> -newPassword - ` as `sg-admin`; update the password manager |
| 3 | Remove their SSH key | delete their line from `~sg-<wing>/.ssh/authorized_keys` on each wing |
| 4 | Rotate the wing's gateway key | `04-GATEWAY.md`; reissue to the remaining seats |

Rotating the gateway key is the step people skip. Skip it and a copied key still reaches the
gateway from anywhere on the tailnet.

## Audit with a shared user

`sg-coding` in a macOS log does not say who. Three things do:

**1. The actor name in every Snow Gloves action.** Set it in the session; approvals record it:

```bash
export SNOWGLOVES_ACTOR="<your name>"
python3 scripts/approvals.py approve --tenant <brand> --id <ticket> --actor "$SNOWGLOVES_ACTOR"
```

`--actor` is being added to `scripts/approvals.py` as part of this fleet change; until it lands,
put the name in `--reason`. Unset actor means the ticket shows the operator user only, which is the
thing we are trying to avoid; make `SNOWGLOVES_ACTOR` part of the person's shell rc on the wing.

**2. Tailscale node identity on connect.** Every Screen Sharing or SSH connection arrives from a
tailnet address that belongs to one person's device. On the wing:

```bash
log show --last 24h --predicate 'process == "screensharingd"' | grep -i -E "authenticat|connect"
log show --last 24h --predicate 'process == "sshd"' | grep -i "accepted"
tailscale whois 100.x.y.z        # maps the source address in those lines to a login and device
```

The Tailscale admin console also keeps per-device connection logs (and network flow logs if
enabled on the plan). That is the authoritative "who was connected when".

**3. Per-person SSH keys.** `sshd` logs the key fingerprint it accepted; the comment in
`authorized_keys` names the person. `ssh-keygen -lf ~/.ssh/authorized_keys` lists fingerprints
next to names.

What this does not give you: who typed at the physical keyboard in Paris. For that, the office is
small enough to ask. If that stops being true, the next step is one macOS user per person
([01-APPLE-ACCOUNT.md](01-APPLE-ACCOUNT.md), the Apple Business Manager section).

## Roles, in specs/005 terms

| Person | Fleet seat | Closest specs/005 role | Note |
|---|---|---|---|
| founder | all wings, `sg-admin`, ARD | portfolio owner + node maintainer | the only one who installs or rotates |
| team member on a wing | that wing's operator user | brand operator | drafts and proposes; approvals stay with the approver role |
| nobody yet | | campaign approver, auditor | assigned per tenant when live delivery is enabled |

The seat gives access to a machine. The role gives authority inside a tenant. They stay separate
on purpose.

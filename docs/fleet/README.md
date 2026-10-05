# Snow Gloves fleet: three Mac minis, one gateway

Thoughtseed Private Limited runs Snow Gloves OS on three Mac minis in the Paris office, split by
function: a **Marketing Mac**, a **Design Mac** and a **Coding Mac**. The Coding Mac is always on and
hosts the shared OmniRoute gateway (port 20128) and Hermes (port 4100) for the whole fleet. The
founder's current mini is the **authoring seat**: configuration is built and tested there, then
handed to the Paris Coding Mac as a gateway kit.

This supersedes the coordinator/worker role split in `docs/MAC-MINI-NODE-ONBOARDING-PLAN.md` and
`docs/AXTECH-REMOTE-WORKSPACE-DRAFT.md` with a function split. The single-machine software install
stays `docs/MAC-MINI-SETUP.md`; this folder is what sits around it.

**Status:** Software: documented and tested on the authoring seat. Physical minis: pending (see
[RECONCILIATION-2026-10-02.md](RECONCILIATION-2026-10-02.md) and the pilot in `ISA.md`).

## The spine: ten steps per mini

Run them in order on each mini. `<wing>` is `marketing`, `design` or `coding`; names come from
`fleet.yaml` at the repo root.

### 0. Company ([00-COMPANY.md](00-COMPANY.md))

Thoughtseed operates the fleet; Axtech is the portfolio root over ten brand tenants (HeyZack, Ecoled,
Kartezzi, Izzimo, Wave, Sunfeed, CEE Management, China Sourcing, Metagration, and AXIO under
Metagration), confirmed by the founder on 2026-10-05. All wings serve all brands.

```bash
cat fleet.yaml
```

### 1. Apple Account and users ([01-APPLE-ACCOUNT.md](01-APPLE-ACCOUNT.md))

Sign in the one company Apple Account, create `sg-admin` (admin) and `sg-<wing>` (standard, the
daily operator), FileVault on, auto-login off, never sleep.

```bash
bash scripts/fleet/remote_access.sh --wing <wing>          # dry-run: prints the user/power commands
```

### 2. Tailscale ([02-NETWORK-REMOTE-ACCESS.md](02-NETWORK-REMOTE-ACCESS.md))

Every mini and every team Mac joins the tailnet. MagicDNS names are the `overlay` values in
`fleet.yaml`: `marketing-mac`, `design-mac`, `coding-mac`.

```bash
sudo tailscale up && sudo tailscale set --hostname <wing>-mac && tailscale status
```

### 3. Remote access: ARD, Screen Sharing, SSH (same doc: [02-NETWORK-REMOTE-ACCESS.md](02-NETWORK-REMOTE-ACCESS.md))

Remote Management on (Apple Remote Desktop for the founder, built-in Screen Sharing for the team),
Remote Login on for `sg-admin` and `sg-<wing>`. Dry-run first, then `--apply` on the mini itself.

```bash
bash scripts/fleet/remote_access.sh --wing <wing> --apply
```

### 4. Machine profile ([03-MACHINE-PROFILES.md](03-MACHINE-PROFILES.md))

Each wing has a node profile under `nodes/`: what it runs, what it must never run, which runtimes
it renders.

```bash
python3 scripts/fleet/node_profile.py show <wing>
```

### 5. Runtimes (`docs/MAC-MINI-SETUP.md`, then [03-MACHINE-PROFILES.md](03-MACHINE-PROFILES.md))

Install the software per the single-machine guide, then render each brand's runtime files for this
wing (dry-run prints, `--write` writes).

```bash
python3 scripts/fleet/node_profile.py render --tenant <brand> --node <wing> --runtime <rt> --write
```

### 6. Gateway ([04-GATEWAY.md](04-GATEWAY.md), also the gateway kit export)

Point the wing at the shared OmniRoute on the Coding Mac. The key never goes in a file; it lives in
the operator user's Keychain under the name the command references.

```bash
python3 scripts/fleet/gateway_client.py set-url --host coding-mac --key-ref keychain:snowgloves-gateway-<wing>
```

### 7. Brands ([05-BRANDS.md](05-BRANDS.md))

Enable every brand tenant on this wing. A wing never owns a brand; it serves all of them.

```bash
python3 scripts/fleet/node_profile.py enable --all-tenants --node <wing>
```

### 8. Team access ([06-TEAM-ACCESS.md](06-TEAM-ACCESS.md))

A seat is a person's own Tailscale login plus the wing operator user plus a scoped gateway key.
Onboard and offboard with the checklists; team members connect with one command.

```bash
bash scripts/fleet/connect.sh <wing>            # Screen Sharing; add "ssh" for a shell
```

### 9. Operate ([07-OPERATIONS.md](07-OPERATIONS.md))

Daily health, weekly upgrades, the Coding Mac reboot checklist, backups, incidents.

```bash
make fleet-doctor
```

## What is where

| Path | Holds | Unit |
|---|---|---|
| `tenants/<slug>/` | one brand: enabled modules, approvals, audit, runtime files | brand |
| `nodes/<wing>/` | one machine profile: allowed runtimes, services, forbidden modules | wing |
| `fleet.yaml` | the inventory: hostnames, overlay names, users, gateway, services | fleet |
| `docs/fleet/` | this flow, numbered in the order you do it | people |
| `docs/MAC-MINI-SETUP.md` | the software install for one machine, unchanged | machine |
| [PROVIDERS.md](PROVIDERS.md), [DECISIONS.md](DECISIONS.md), [RECONCILIATION-2026-10-02.md](RECONCILIATION-2026-10-02.md) | providers per wing; why Tailscale, one Apple Account, shared operator users; proven vs pending | reference |

## Two rules that hold everywhere

- No secrets in git (not in `fleet.yaml`, `nodes/` or docs); Keychain and the company password
  manager hold them. Dry-run is the default for every fleet script; only `--apply` and `--write` change anything.
- A trusted mini or a shared Apple Account is not an organization principal
  (`specs/005-node-bootstrap/spec.md`). Brand permissions come from the tenant, never from the box.

Note on names: the Coding Mac already exists as "AXIO’s Mac mini" with operator user `mac-coding`; `fleet.yaml` records that (`lan_host`, `operator_user`) and is the source of truth. The `sg-<wing>` convention applies to the two new minis. Until Tailscale is up, pass `--lan` to `connect.sh` and use `gateway.lan_url`.

Pickup for a new session: [HANDOFF-2026-10-05.md](HANDOFF-2026-10-05.md).

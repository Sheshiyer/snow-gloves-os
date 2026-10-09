# Snow Gloves fleet: four Mac minis, three wings

The fleet has four canonical device slots: **Mac Coding 01**, **Mac Coding 02**, **Mac Creative** and **Mac Marketing**. The two coding devices share the `coding` wing policy; Creative uses `design`, and Marketing uses `marketing`. These are four physical assignments and three capability profiles.

Start with the [100-point onboarding checklist](ONBOARDING-100.md), the [repeatable local runbook](LOCAL-FIRST-TEST.md) and [capability transition map](CAPABILITY-TRANSITION.md). The [fleet world contract](../fleet-world.md) defines explicit unique private island assignments. The current Mac Coding 01 is the first local onboarding reference. Each other Mac needs its own identity and test evidence.

Platform source belongs here. Fleet identity, tenants, receipts and device-specific configuration belong in the separate private `snow-gloves-ops` checkout. A configured island is inventory metadata; device, runtime, connector, reboot and capacity tests retain separate acceptance.

The existing operations workspace supports owned foreground loopback startup. The historical resumable bootstrap CLI remains unimplemented. The commands below describe individual tools and policies; do not run the legacy global installer or port-killing smoke target as the local first test. Gateway placement and service activation require observed device-specific configuration.

## The spine: ten steps per mini

Use this policy spine alongside the current local runbook; inspect each command before changing host settings. `<wing>` is `marketing`, `design` or `coding`; names come from
`fleet.yaml` in the data checkout (start a new one from `fleet.example.yaml`).

### 0. Company and data checkout (private: `snow-gloves-ops/docs/fleet/00-COMPANY.md`)

One operator company runs the fleet. A portfolio root tenant sits over the brand tenants, and all
wings serve all brands. The portfolio, its brands and the company record live in the private ops
repo, not here.

```bash
export SNOWGLOVES_DATA=/path/to/snow-gloves-ops   # tenants/, fleet.yaml, nodes/
python3 scripts/ops_workspace.py check --data-root "$SNOWGLOVES_DATA"  # safe summary; raw inventory stays private
```

### 1. Apple Account and users ([01-APPLE-ACCOUNT.md](01-APPLE-ACCOUNT.md))

Sign in the one company Apple Account, create `sg-admin` (admin) and `sg-<wing>` (standard, the
daily operator), FileVault on, auto-login off, never sleep.

```bash
bash scripts/fleet/remote_access.sh --wing <wing>          # dry-run: prints the user/power commands
```

### 2. Tailscale ([02-NETWORK-REMOTE-ACCESS.md](02-NETWORK-REMOTE-ACCESS.md))

Every mini and every team Mac joins the tailnet. Each physical device needs a unique MagicDNS name recorded in its private island inventory. The two coding devices must not reuse the same hostname.

```bash
sudo tailscale up
sudo tailscale set --hostname <reviewed-unique-device-name>
tailscale status
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

With a cloud gateway ([08-CLOUD-GATEWAY.md](08-CLOUD-GATEWAY.md)) the same command takes `--url https://gw.<zone>`.

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
| `$SNOWGLOVES_DATA/tenants/<slug>/` | one brand: enabled modules, approvals, audit, runtime files (this repo keeps only fixtures) | brand |
| `nodes/<wing>/` | one machine profile: allowed runtimes, services, forbidden modules (templates here; the instance copy in the data checkout wins) | wing |
| `$SNOWGLOVES_DATA/fleet.yaml` | the inventory: hostnames, overlay names, users, gateway, services (template: `fleet.example.yaml`) | fleet |
| `docs/fleet/` | this flow, numbered in the order you do it | people |
| `docs/MAC-MINI-SETUP.md` | the software install for one machine, unchanged | machine |
| `snow-gloves-ops/docs/fleet/{PROVIDERS,DECISIONS,RECONCILIATION-2026-10-02}.md` (private) | providers per wing; why Tailscale, one Apple Account, operator users; proven vs pending | reference |

## Two rules that hold everywhere

- No secrets in git (not in `fleet.yaml`, `nodes/` or docs); Keychain and the company password
  manager hold them. Instance data (tenants, `fleet.yaml`, receipts, planning) never goes in this repo. Dry-run is the default for every fleet script; only `--apply` and `--write` change anything.
- A trusted mini or a shared Apple Account is not an organization principal
  (`specs/005-node-bootstrap/spec.md`). Brand permissions come from the tenant, never from the box.

Note on names: a machine that already exists can keep its LAN name and local user; the private
`fleet.yaml` records them (`lan_host`, `operator_user`) and is the source of truth. The `sg-<wing>`
convention applies to new minis. Until Tailscale is up, pass `--lan` to `connect.sh` and use
`gateway.lan_url`.

Session handoffs live with the instance data: `snow-gloves-ops/docs/fleet/` and `snow-gloves-ops/.planning/` (private).

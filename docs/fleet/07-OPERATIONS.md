# 07. Operations: daily, weekly, after a reboot, backups, incidents

Step 9 of the [README](README.md). Everything here is run as the wing operator user unless it
says `sudo`.

## Daily

```bash
make fleet-doctor
```

On any wing it checks the machine profile, the tenants enabled on it, and whether the gateway
answers. On the Coding Mac it also checks OmniRoute and Hermes locally. From the founder's Mac,
Apple Remote Desktop > Send UNIX Command to all three minis runs the same thing fleet-wide
([02-NETWORK-REMOTE-ACCESS.md](02-NETWORK-REMOTE-ACCESS.md)). Green is boring; a warning that
repeats two days in a row is a ticket.

## Weekly

Bring each brand tenant forward to the platform version. Dry-run first, read the diff, then write.

```bash
make upgrade T=<brand>            # dry-run: shows the diff and the adapters it would re-render
make upgrade T=<brand> WRITE=1    # apply; safe to run twice
```

Details in `docs/UPGRADING.md`. Do it on one wing; tenants live in git, so the other wings pick
the change up on their next `git pull`. Then `make fleet-doctor` on each wing.

Also weekly: `tailscale status` on the Coding Mac (all three minis online, key expiry disabled),
and a glance at free disk on the Design Mac (media fills disks first).

## After a reboot of the Coding Mac

The Coding Mac is the gateway; when it is down every wing's model routing is down. In order:

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | FileVault unlocked and `sg-coding` logged in | someone in Paris, or Screen Sharing to the login window if the daemon-variant Tailscale is up | login window gone |
| 2 | Tailscale up | `tailscale status` | `coding-mac` listed, peers visible |
| 3 | OmniRoute LaunchAgent running | `launchctl print gui/$(id -u) \| grep -i omniroute` and `curl -s http://127.0.0.1:20128/healthz` | an agent line; a 200 body |
| 4 | Hermes listening | `lsof -i tcp:4100` | a `python` process |
| 5 | Reachable from a wing | on `marketing-mac`: `curl -s http://coding-mac:20128/healthz` | same 200 body |
| 6 | Fleet view | `make fleet-doctor` | green |

If step 3 fails, the LaunchAgent label and plist path are in [04-GATEWAY.md](04-GATEWAY.md);
`launchctl kickstart -k gui/$(id -u)/<label>` restarts it. If step 4 fails: Hermes is not a
LaunchAgent in the single-machine guide (`make hermes` runs it in the foreground). On the Coding Mac
run it inside a `tmux` session named `hermes` so it survives a dropped Screen Sharing session, or
install the LaunchAgent that 04-GATEWAY.md provides. Planned reboots: `sudo fdesetup authrestart`
skips the FileVault unlock once.

## Backups: what lives where

| Lives in git (push it) | Lives on the host only (export it) | Never copied anywhere |
|---|---|---|
| `tenants/<brand>/` (enabled modules, approvals, audit, rendered runtime files) | OmniRoute data in `~/.omniroute` on the Coding Mac (sqlite, provider sessions, logs) | API keys, gateway keys, operator passwords |
| `nodes/<wing>/` machine profiles | Keychain of each operator user (gateway key, Screen Sharing passwords) | FileVault recovery keys (password manager only) |
| `fleet.yaml`, `docs/fleet/` | Tailscale state (`/var/lib/tailscale` or the app's container) | Apple Account credentials |

The gateway kit in [04-GATEWAY.md](04-GATEWAY.md) is how the non-secret host state of the Coding
Mac moves: it exports the OmniRoute configuration and combo map without the sqlite or any session,
so the authoring seat can rebuild a Coding Mac from the kit plus the password manager. Rehearse that
once before the minis ship; a backup that has never been restored is a hope.

Time Machine on the minis is optional and must exclude `~/.omniroute` (live sqlite) and any
tenant `_embed_cache/`. The authoritative copy of everything that matters is git plus the password
manager plus the kit.

## Incidents

| Incident | Who degrades | First command | Recovery |
|---|---|---|---|
| Gateway down (OmniRoute not answering on 20128) | all wings lose model routing; local-only work (`make walk`, `make doctor`, editing tenants) continues | on the Coding Mac: `curl -s http://127.0.0.1:20128/healthz` | restart the LaunchAgent (above). If the Coding Mac itself is down and you need a wing working now, point that wing at a temporary local OmniRoute (below). |
| Coding Mac off after power loss | same as above, plus Hermes events stop | `tailscale status` from any Mac | someone in Paris unlocks FileVault; then the reboot checklist |
| Office internet down | Tailscale direct connections inside the office still work over the LAN; remote access does not | from a wing: `ping coding-mac` | wait; nothing to fix on the minis |
| Tailscale key or ACL mistake | the affected wing is unreachable remotely | admin console > Machines | re-enable, disable expiry; the office keyboard still works |
| Gateway key leaked | anyone on the tailnet with the key can spend | rotate per [06-TEAM-ACCESS.md](06-TEAM-ACCESS.md) | reissue to seats |
| Design Mac disk full | that wing's renders fail | `df -h /` | clear `_embed_cache/` and media exports; the brand tenant in git is unaffected |
| A wing's runtime renders stale files | that wing only | `python3 scripts/fleet/node_profile.py render --tenant <brand> --node <wing> --runtime <rt>` | dry-run, then `--write` |

### Temporary local OmniRoute on a wing

Only when the Coding Mac is down for longer than the work can wait, and only on one wing at a time.

```bash
# on the wing, if OmniRoute is installed locally per 04-GATEWAY.md (it is not by default)
python3 scripts/fleet/gateway_client.py set-url --host 127.0.0.1 --key-ref keychain:snowgloves-gateway-<wing>
# ... work ...
python3 scripts/fleet/gateway_client.py set-url --host coding-mac --key-ref keychain:snowgloves-gateway-<wing>
```

Point it back the moment the Coding Mac returns. Two gateways with different provider state is the
situation `docs/AXTECH-REMOTE-WORKSPACE-DRAFT.md` warns about ("do not dual-write competing
authorities"); a temporary local gateway is a stopgap, not a second seat.

## What is not operated here

- Provider budgets and failover combos: host OmniRoute and `~/.temperance_engine` ([PROVIDERS.md](PROVIDERS.md)).
- Brand approvals and campaign sends: the tenant's approvals queue (`make approvals T=<brand>`).
- The physical minis before they exist: [RECONCILIATION-2026-10-02.md](RECONCILIATION-2026-10-02.md).

## Changing the gateway bind address

Edit `OMNIROUTE_SERVER_HOST` in `~/Library/LaunchAgents/com.temperance.engine.omniroute.plist` (or re-run
`gateway_kit.sh import <tar> --apply --bind-ip <ip>`), then `launchctl bootout gui/$(id -u)/com.temperance.engine.omniroute`
and `launchctl bootstrap gui/$(id -u) <plist>`. A bare `launchctl kickstart -k` restarts the process with the old
environment and the bind does not move. Verified on the Coding Mac on 2026-10-02.

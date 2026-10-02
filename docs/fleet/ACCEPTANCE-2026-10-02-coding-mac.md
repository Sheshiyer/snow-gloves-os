# Acceptance receipt: Coding Mac gateway, 2026-10-02

Evidence is reported separately for the source tree, the local installation on the authoring seat, and the physical mini.

## Source (this repository, branch `codex/local-mini-pilot`)

| Item | Evidence |
|---|---|
| Commits | `ae004d1` fleet wings, `df63551` kit install path + LAN bind, `7bcbbb9` LAN name |
| Tests | `python3 -m pytest -q` → 264 passed; `scripts/build_catalog.py --check` → up to date |
| Kit | `scripts/fleet/gateway_kit.sh export --bind-ip 192.168.0.35` → 16 files, `verify: OK`, pinned `omniroute-version.txt` = 3.8.50 |

## Local installation (authoring seat, "Sheshnarayan's Mac mini")

| Item | Evidence |
|---|---|
| OmniRoute | `/opt/homebrew/bin/omniroute` 3.8.50, LaunchAgent `com.temperance.engine.omniroute`, bound to 127.0.0.1:20128 |
| Database snapshot | `sqlite3 .backup` of `~/.omniroute/storage.sqlite` (201.7 MB), `integrity_check` ok on the copy; 29 provider connections, 21 combos, 6 api keys |
| Transfer | `~/.omniroute/.env` (storage key) and the snapshot copied over SSH to the Coding Mac (route A); nothing placed in the kit |
| Access | fleet key `~/.ssh/snowgloves-fleet`, SSH alias `coding-mac` → `mac-coding.local`, user `mac-coding` (alias of `axio`) |

## Physical mini (Coding Mac, "AXIO's Mac mini", Mac16,10)

| Item | Evidence |
|---|---|
| Hardware | Apple M4, 10 cores, 16 GB RAM, 228 GB disk (160 GB free), macOS 27.0.1 (26A434) |
| Identity | short name `axio` (uid 501, admin, only user), home `/Users/axio`, LocalHostName `mac-coding`, LAN 192.168.0.35 on en1 |
| Access | Remote Login on (key auth works), Remote Management on (ARDAgent running), firewall disabled |
| Toolchain | Homebrew, node v22.23.3, git 2.56, Xcode CLT; Python 3.14.8 + PyYAML installed this session |
| Repo | `~/snow-gloves-os` mirrored by rsync at `7bcbbb9` (git bundle failed on a pre-existing history hole at `3353e52`) |
| Kit import | `import --bind-ip 192.168.0.35 --apply`: `npm install -g omniroute@3.8.50` (1175 packages, 42 s), `.env` present (seat key), plist written, LaunchAgent bootstrapped, lane template + phase combo core seeded |
| Service | `launchctl` state running; `node 192.168.0.35:20128` listening; `/healthz` 200 on the LAN address; loopback refused (single-address bind, by design) |
| Route test from the seat | `GET /v1/models` 200 (5380 models, all 19 `noesis-*` combos); `POST /v1/chat/completions` model `noesis-fast` → `GATEWAY-OK` (served by `poolside/laguna-s-2.1-free`, 5.0 s); `POST /v1/messages` model `noesis-orchestrator` → `MESSAGES-OK` (served by `gpt-5.6-terra`, 2.8 s) |
| Runtimes on the mini | Claude Code 2.1.287 and Codex 0.160.0 installed (npm globals); both pointed at `http://192.168.0.35:20128` by `gateway_client.py`; `claude -p` via `noesis-fast` → `NODE-CLAUDE-OK`; `codex exec -m noesis-fast` → `NODE-CODEX-OK`. Key lives in `~/.config/snowgloves/gateway.key` (600) and `~/.zshenv` exports it; the login keychain cannot be written over SSH (no GUI session) |
| Fleet doctor on the mini | critical checks pass; warnings: ComputerName not renamed, Tailscale not installed, Hermes not running, the mini's own runtime configs not yet pointed at the gateway |

## Tailnet milestone (same day, 13:20 UTC)

| Item | Evidence |
|---|---|
| Tailscale on the mini | `tailscaled` installed as a system daemon (Homebrew formula 1.102.5), `tailscale up --hostname coding-mac`; device `coding-mac.tail32e298.ts.net`, 100.117.187.123, tailnet `heyzackai@gmail.com` |
| Power policy | `pmset -a sleep 0 displaysleep 10 autorestart 1 womp 1` applied (`autorestart 1; sleep 0; displaysleep 10; womp 1`) |
| Gateway rebind | plist `OMNIROUTE_SERVER_HOST` 192.168.0.35 → 100.117.187.123, LaunchAgent bootout + bootstrap (a bare `kickstart -k` keeps the old environment); `node 100.117.187.123:20128` listening; `/healthz` 200 via the IP and via `http://coding-mac:20128`; LAN address now 000 |
| Mini's own clients | Claude Code and Codex re-pointed to `http://coding-mac:20128`; `claude -p` → `TAILNET-CLAUDE-OK`; `codex exec` → `TAILNET-CODEX-OK` |
| Seat on the tailnet | `authoring-mini` 100.77.42.94 joined the same tailnet (13:35 UTC). From the seat: `http://coding-mac:20128/healthz` 200, SSH to `axio@coding-mac` over the overlay, `POST /v1/chat/completions` model `noesis-fast` → `OVERLAY-OK` (served by `gemini-3.7-flash-low`, 2.0 s); LAN address 000; `doctor.py` reports tailscale running and the fleet gateway ok |

## Cutover (same day, 14:10 UTC)

| Item | Evidence |
|---|---|
| Seat clients | `gateway_client.py set-url --host coding-mac --apply`: Claude Code, Codex, Grok, OpenCode all report FLEET; the seat's own Codex `[model_providers.omniroute]` table (outside the managed block) edited by hand to `http://coding-mac:20128/v1` |
| Seat gateway | LaunchAgent `com.temperance.engine.omniroute` now runs a loopback-only socat forwarder to 100.117.187.123:20128; no `omniroute serve` process on the seat; `launchctl enable` was needed before `bootstrap` (first attempt returned error 5) |
| Loopback path | `127.0.0.1:20128/healthz` 200; `/v1/models` 5380; chat via `noesis-fast` → `CUTOVER-OK`; Temperance manifest bridge healthy |
| Direct path | `coding-mac:20128` chat → `CUTOVER-OK` (2.4 s); `/v1/messages` 200 for `noesis-fast` and `noesis-orchestrator` |
| Seat Claude Code | `claude -p` → `SEAT-CLAUDE-OK` and `SEAT-CLAUDE-DEFAULT-OK` with a clean environment. Note: a Claude Code *session* exports `ANTHROPIC_BASE_URL=https://api.anthropic.com`, which overrides settings.json for child processes, so tests must be run outside such a session |
| Seat Codex | the user's omniroute provider table uses `env_key = "OPENAI_API_KEY"`; see the decision log for the verification line |
| Backups | `~/.snowgloves-cutover-backup-20261002T140733Z/` holds the previous plist and the four client configs |

## Not yet done

- Tailscale: done on the Coding Mac and the seat; the two other minis still have to join.
- Power policy needs sudo on the mini: `sudo pmset -a sleep 0 displaysleep 10 autorestart 1 womp 1`.
- Cutover done: the Coding Mac is the only live gateway; the seat forwards loopback to it.
- Scoped keys per machine and per person are not minted yet; the mirrored seat client key is in use on the mini for the test (key file, not Keychain).
- Hermes on the coding wing, the Coding Mac's own CLI configs, and the two other minis.

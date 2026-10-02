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
| Fleet doctor on the mini | critical checks pass; warnings: ComputerName not renamed, Tailscale not installed, Hermes not running, the mini's own runtime configs not yet pointed at the gateway |

## Not yet done

- Tailscale: binary installed on the Coding Mac this session; `tailscale up` is interactive and the founder's step. Until then the gateway is LAN-only (`gateway.lan_url`).
- Power policy needs sudo on the mini: `sudo pmset -a sleep 0 displaysleep 10 autorestart 1 womp 1`.
- Both machines now hold the same OAuth seats and both run a gateway. Providers that rotate refresh tokens can invalidate one side. Decide the cutover: make the Coding Mac the only live gateway and point the seat's clients at it, or stop the seat's agent.
- Scoped keys per machine and per person are not minted yet; the mirrored admin/client keys are in use for the test.
- Hermes on the coding wing, the Coding Mac's own CLI configs, and the two other minis.

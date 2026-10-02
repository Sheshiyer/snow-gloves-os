# 04. Shared gateway: OmniRoute on the Coding Mac

One OmniRoute instance serves every wing. It runs on the always-on Coding Mac in Paris, listens only
on that machine's Tailscale address, and holds every provider seat (API keys and subscription sign-ins).
The founder's current Mac mini is the authoring seat: it edits this repo and exports a handoff kit; it
does not serve the fleet. Decisions behind this layout: [DECISIONS.md](DECISIONS.md). Provider roster
and wing defaults: [PROVIDERS.md](PROVIDERS.md).

## Topology

```
 Founder's current Mac mini (authoring seat, role staging)
   edits fleet.yaml, nodes/, docs; its own OmniRoute stays on 127.0.0.1
   bash scripts/fleet/gateway_kit.sh export  ->  dist/fleet/gateway-kit-<stamp>.tar.gz
                   |
                   |  Taildrop or scp over the tailnet (kit carries no secrets)
                   v
 Coding Mac, Paris office, always on                       <- the gateway host
   LaunchAgent com.temperance.engine.omniroute
   OMNIROUTE_SERVER_HOST=<tailscale ip>  ->  listens on <tailscale ip>:20128 only
   provider seats (API keys, OAuth sign-ins) exist only here
                   ^
                   |  tailnet, MagicDNS name coding-mac
   +---------------+---------------+---------------------+
   |               |               |                     |
 marketing-mac   design-mac     coding-mac itself     team Macs
 sg-marketing    sg-design      sg-coding             one person, one scoped key
   Claude Code, Codex, Grok CLI, OpenCode, Cursor  ->  http://coding-mac:20128
```

## Bind policy: the Tailscale IP, never 0.0.0.0

- Find the address on the Coding Mac: `tailscale ip -4` (a 100.64.0.0/10 address).
- Set it in the LaunchAgent: `OMNIROUTE_SERVER_HOST=<tailscale-ip>` under `EnvironmentVariables` in
  `~/Library/LaunchAgents/com.temperance.engine.omniroute.plist`. The kit import writes this for you.
  Reload in the user domain, never with sudo: `launchctl bootout gui/$(id -u)/com.temperance.engine.omniroute`
  then `launchctl bootstrap gui/$(id -u) <plist>` and `launchctl kickstart -k gui/$(id -u)/com.temperance.engine.omniroute`.
- Why not `0.0.0.0`: it binds every interface, including office Wi-Fi and any future tunnel. The gateway
  code treats the whole 100.64.0.0/10 range as "private LAN", so on an all-interfaces socket the only
  thing between a visitor on the office network and the management API is the dashboard password.
  Binding to the tailnet address means only devices admitted to the company tailnet, and allowed by its
  ACLs, can open the port. Add a Tailscale ACL that allows tcp/20128 to `coding-mac` from company devices only.
- Consequence: loopback is not bound. Clients running on the Coding Mac itself also use
  `http://coding-mac:20128` (MagicDNS resolves to the host's own tailnet address), not `127.0.0.1`.
  The host-side comment in `fleet.yaml` saying the host uses `127.0.0.1` needs updating by the inventory owner.
- Proof: `lsof -nP -iTCP:20128 -sTCP:LISTEN` on the host shows `<tailscale-ip>:20128`, not `*:20128`.

Consequence of the single-address bind, verified on the Coding Mac on 2026-10-02: `127.0.0.1:20128` is refused on the
host itself. Clients running on the Coding Mac use its LAN or Tailscale address, not loopback, and the Temperance
fleet sync script (which only addresses loopback) must be pointed at that address or run with a loopback alias.

## Keys

- The admin key (the `Temperance Engine` row in `api_keys`, loaded by `~/.omniroute/export-api-key.sh`)
  can delete providers and combos and purge the call log. It never leaves the Coding Mac. Host jobs use it; people do not.
- One scoped key per machine and per person, minted in the dashboard (Settings, API Keys) and named
  `sg-<wing>-<hostname>` or `sg-<person>`. Scope it with the existing `api_keys` columns:
  `allowed_endpoints = ["chat","models"]`, `allowed_combos` (that wing's combos), `ip_allowlist` (that
  machine's tailnet address), `daily_usage_limit_usd`. Read-only tooling (status pages, doctor scripts)
  gets a `cli_access_tokens` row with `scope = 'read'` instead of an API key.
- Clients keep their key in the login Keychain under service `snowgloves-gateway-<wing>` (node profiles
  reference it as `key_ref: keychain:snowgloves-gateway-<wing>`). Store it interactively so the value
  never lands in shell history: `security add-generic-password -a snowgloves -s snowgloves-gateway-<wing> -w`.
- Rotation: quarterly, and immediately on any exposure (screenshot, log line, shared doc). Mint the new
  key, update the Keychain item, run `gateway_client.py set-url --apply`, confirm with `status`, then
  revoke the old key in the dashboard. Rotate the dashboard password at import time; the default is still in play.

## Provider classes

| Class | Examples | How it is shared |
|---|---|---|
| API-key provider, pay per token | openai, cheaperinference, openrouter, nvidia, nous, gemini, alibaba | One company key per provider, held by the gateway. Ordinary API usage. |
| Subscription seat, OAuth or session | Claude Max (`claude`), ChatGPT Codex (`codex`), SuperGrok (`grok`), Cursor, Antigravity, Command Code plan | Signed in once on the Coding Mac; tokens stay there. Provider terms for multi-user use are not yet confirmed. |

Founder decision 2026-10-02: share all seats now, including subscription seats, and confirm terms later.
This overrides the host-side ACP rule that prohibited it. Risk, mitigations and the review date are in
[DECISIONS.md](DECISIONS.md).

## Add a provider

1. Connect it on the Coding Mac: dashboard Providers, add connection, run its test. Note the connection id.
2. Seat it in the lane template `~/.temperance_engine/state/lane-templates-from-live.json` using the
   sqlite form `provider/model` (not the UI form).
3. Dry-run: `python3 ~/.agents/skills/temperance-parallel-dispatch/scripts/sync-provider-fleet.py`.
   Read the planned seat changes and the `errored_providers` list.
4. Apply: the same command with `--apply`.
5. Readback: `sqlite3 -readonly ~/.omniroute/storage.sqlite "SELECT name, json_extract(data,'$.models[0]') FROM combos WHERE name LIKE 'noesis-%' ORDER BY name;"`
   and `curl -s -H "Authorization: Bearer $OMNIROUTE_API_KEY" http://coding-mac:20128/v1/models | grep -c noesis-`.
6. Add the row to [PROVIDERS.md](PROVIDERS.md).

Never hand-edit combos, in the dashboard or in sqlite. The 15-minute `session-rebalance` job rewrites
every templated combo from the lane template, so a hand edit is reverted and leaves a stale marker.

## Client setup (any wing Mac or team Mac)

```bash
python3 scripts/fleet/gateway_client.py set-url --host coding-mac --key-ref keychain:snowgloves-gateway-<wing>          # dry-run: unified diff per file
python3 scripts/fleet/gateway_client.py set-url --host coding-mac --key-ref keychain:snowgloves-gateway-<wing> --apply  # writes, .bak next to each file
python3 scripts/fleet/gateway_client.py status                                                                          # FLEET / NOT-FLEET per surface + /healthz
python3 scripts/fleet/gateway_client.py doctor --key-ref keychain:snowgloves-gateway-<wing>                             # + tailscale + key_ref FOUND/MISSING
```

| Surface | File | What is written |
|---|---|---|
| Claude Code | `~/.claude/settings.json` | `env.ANTHROPIC_BASE_URL = http://coding-mac:20128` (root, no `/v1`), `env.ANTHROPIC_AUTH_TOKEN` = the key, read from the key_ref at apply time, shown only as `[redacted]` |
| Codex | `~/.codex/config.toml` | `[model_providers.omniroute]` with `base_url = .../v1`, `env_key = "OMNIROUTE_API_KEY"`, plus top-level `model_provider = "omniroute"` if absent |
| Grok CLI | `~/.grok/config.toml` | `[model.te-orchestrator|build|fast|plan]` blocks, `base_url = .../v1`, `env_key = ["OMNIROUTE_API_KEY"]`, `model = "noesis-*"` |
| OpenCode | `~/.config/opencode/opencode.json` | `provider.omniroute.options.baseURL = .../v1`, `apiKey = "{env:OMNIROUTE_API_KEY}"` |

TOML blocks are appended once and reported as `present` afterwards; unrelated keys are never rewritten.
Codex, Grok and OpenCode read the key from the environment, so add to the shell profile:
`export OMNIROUTE_API_KEY="$(security find-generic-password -s snowgloves-gateway-<wing> -w)"`.
On the authoring mini keep Codex native: pass `--surfaces claude,grok,opencode`.

## Paris handoff

What the Coding Mac needs before anything else: macOS signed in, Remote Login (SSH) and Remote Management on,
Homebrew and node installed. OmniRoute itself is an npm global package (`npm install -g omniroute@<version>`);
the authoring seat runs 3.8.50 from Homebrew's node and the kit records that version.

1. Authoring seat: `bash scripts/fleet/gateway_kit.sh export` (add `--bind-ip <ip>` when the Coding Mac's
   Tailscale or LAN address is known). The kit holds `fleet.yaml`, `nodes/`, a `host/` folder (lane template,
   phase combo core, the LaunchAgent plist with secret-shaped values replaced by `REDACTED` and the bind host
   replaced by `${TAILSCALE_IP}`, `providers.txt`, `omniroute-version.txt`), `client-templates/` and
   `README-IMPORT.md`. A leak guard aborts the export if anything secret-shaped is staged.
2. Move it: `scp dist/fleet/gateway-kit-*.tar.gz coding-mac:~/` (the `coding-mac` SSH alias points at
   `axios-mac-mini.local` today and at the Tailscale name later) or Taildrop once the tailnet is up.
3. Coding Mac, over SSH or Screen Sharing as `mac-coding`: `verify <tar>`, then `import <tar>` (dry-run, read
   it), then `import <tar> --apply --bind-ip <ip>`. Use the LAN address from `ipconfig getifaddr en0` until
   Tailscale is installed, then re-run with the Tailscale IP. Import installs or aligns OmniRoute, writes a fresh
   storage key, renders and bootstraps the LaunchAgent, seeds the lane template where absent, and prints the
   configuration-transfer options. It never writes a secret.
4. Configuration transfer, by you, over SSH, because providers, combos and keys are secret-bearing and never
   live in the kit:
   - Route A, mirror the seat: copy `~/.omniroute/storage.sqlite` (with `-wal` and `-shm`) and `~/.omniroute/.env`
     from the seat to the Coding Mac, then `launchctl kickstart -k gui/$(id -u)/com.temperance.engine.omniroute`.
     Exact copy of providers, combos, keys and OAuth seats. This is the founder's chosen posture (seats shared).
   - Route B, bundle: on the seat `omniroute sync bundle gw.json --include settings,combos,policies,providers,keys`,
     `scp` it, `omniroute sync import --dry-run gw.json`, then import, then `rm -P gw.json`. On 2026-10-02 the
     seat's CLI key answered 401 to `sync bundle`; fix the key scope first (same runbook as the MCP 403).
   The Temperance fleet sync script only addresses `127.0.0.1:20128`, so it runs on the gateway host, not remotely.
5. Sign-in checklist on the Coding Mac for anything route A did not carry or that a provider re-challenges:
   Claude Code `claude` then `/login`; `codex login`; `grok`; Cursor.app; then in the OmniRoute dashboard check
   `codex`, `claude`, `cursor`, `antigravity`, rotate the dashboard password (`omniroute reset-password`) and mint
   the scoped keys (one per wing, one per person).
6. Point each client with `gateway_client.py set-url --host axios-mac-mini.local` now (`--host coding-mac` once
   Tailscale resolves it) and confirm with `status`; `fleet.yaml` carries both as `gateway.url` and `gateway.lan_url`.

## Health checks

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://coding-mac:20128/healthz        # 200
curl -s -o /dev/null -w '%{http_code}\n' http://coding-mac:20128/v1/models      # 401 without a key is healthy
curl -s -H "Authorization: Bearer $OMNIROUTE_API_KEY" http://coding-mac:20128/v1/models | grep -c noesis-   # > 0
lsof -nP -iTCP:20128 -sTCP:LISTEN                                                 # on the host: <tailscale-ip>:20128
```

## Operator steps outside this repo

These touch `~/.temperance_engine` or the machines themselves and are not done by any script here.

1. Amend rule #4 in `~/.temperance_engine/docs/decisions/ACP-INTEGRATION-2026-08-24.md` (open question 4,
   currently "NO, prohibited until the operator says otherwise") with the dated 2026-10-02 override and a
   pointer to `docs/fleet/DECISIONS.md`. Record there that the "change OMNIROUTE_SERVER_HOST only behind a
   human gate" rail was satisfied by this decision.
2. Rotate the OmniRoute dashboard password on the Coding Mac (`omniroute reset-password`), following
   `~/.temperance_engine/docs/decisions/omniroute-dashboard-password-status.md`.
3. Fix the `omniroute` MCP key scope: mint a key with `mcp-connect`, store it under Keychain service
   `temperance-mcp-connect`, per `~/.temperance_engine/docs/operations/omniroute-mcp-key-rotation.md`.
   The current key answers 403.
4. Install Tailscale on the authoring mini and join the company tailnet; this seat has no `tailscale` binary today.
5. Update the `fleet.yaml` host comment (loopback is not bound once the gateway listens on the tailnet address).
6. Add the Tailscale ACL for tcp/20128.

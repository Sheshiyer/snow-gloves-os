# 04. Shared gateway: OmniRoute on the Coding Mac

One OmniRoute instance serves every wing. It runs on the always-on Coding Mac in the office, listens
only on that machine's Tailscale address, and holds the provider connections (API keys, and the
provider sign-ins the operator is entitled to use on that host). The founder's own Mac is the
authoring seat: it edits this repo and exports a handoff kit; it does not serve the fleet. An
instance's decisions and its provider roster with wing defaults are private:
`snow-gloves-ops/docs/fleet/DECISIONS.md` and `snow-gloves-ops/docs/fleet/PROVIDERS.md`.

## Topology

```
 Founder's own Mac (authoring seat, role staging)
   edits fleet.yaml, nodes/, docs; its own OmniRoute stays on 127.0.0.1
   bash scripts/fleet/gateway_kit.sh export  ->  dist/fleet/gateway-kit-<stamp>.tar.gz
                   |
                   |  Taildrop or scp over the tailnet (kit carries no secrets)
                   v
 Coding Mac, the office, always on                         <- the gateway host
   LaunchAgent com.temperance.engine.omniroute
   OMNIROUTE_SERVER_HOST=<tailscale ip>  ->  listens on <tailscale ip>:20128 only
   provider credentials (API keys, OAuth sign-ins) exist only here
                   ^
                   |  tailnet, MagicDNS name coding-mac
   +---------------+---------------+---------------------+
   |               |               |                     |
 marketing-mac   design-mac     coding-mac itself     team Macs
 sg-marketing    sg-design      sg-coding             one person, one scoped key
   Claude Code, Codex, Grok CLI, OpenCode, Cursor  ->  http://coding-mac:20128
```

## Bind policy: the Tailscale IP, never 0.0.0.0

- Find the address on the Coding Mac: `tailscale ip -4` (an address in Tailscale's CGNAT range, 100.64/10).
- Set it in the LaunchAgent: `OMNIROUTE_SERVER_HOST=<tailscale-ip>` under `EnvironmentVariables` in
  `~/Library/LaunchAgents/com.temperance.engine.omniroute.plist`. The kit import writes this for you.
  Reload in the user domain, never with sudo: `launchctl bootout gui/$(id -u)/com.temperance.engine.omniroute`
  then `launchctl bootstrap gui/$(id -u) <plist>` and `launchctl kickstart -k gui/$(id -u)/com.temperance.engine.omniroute`.
- Why not `0.0.0.0`: it binds every interface, including office Wi-Fi and any future tunnel. The gateway
  code treats the whole CGNAT range (100.64/10) as "private LAN", so on an all-interfaces socket the only
  thing between a visitor on the office network and the management API is the dashboard password.
  Binding to the tailnet address means only devices admitted to the company tailnet, and allowed by its
  ACLs, can open the port. Add a Tailscale ACL that allows tcp/20128 to `coding-mac` from company devices only.
- Consequence: loopback is not bound. Clients running on the Coding Mac itself also use
  `http://coding-mac:20128` (MagicDNS resolves to the host's own tailnet address), not `127.0.0.1`.
  The host-side comment in `fleet.yaml` saying the host uses `127.0.0.1` needs updating by the inventory owner.
- Proof: `lsof -nP -iTCP:20128 -sTCP:LISTEN` on the host shows `<tailscale-ip>:20128`, not `*:20128`.

Consequence of the single-address bind, verified on a Coding Mac: `127.0.0.1:20128` is refused on the
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
  revoke the old key in the dashboard. Rotate the dashboard password at import time, before the gateway serves anyone.

## Provider classes

| Class | Examples | How it is used |
|---|---|---|
| API-key provider, pay per token | openai, cheaperinference, openrouter, nvidia, nous, gemini, alibaba | One company key per provider, held by the gateway. Ordinary API usage. |
| Account sign-in, OAuth or session | provider CLIs and apps that sign in with an account | Signed in on the Coding Mac by the operator, only for accounts the operator is entitled to use there; tokens stay on the host. Check each provider's terms before routing other people's work through an account sign-in. |

Which providers an instance connects, and why, is recorded in its private decisions log
(`snow-gloves-ops/docs/fleet/DECISIONS.md`).

## Add a provider

1. Connect it on the Coding Mac: dashboard Providers, add connection, run its test. Note the connection id.
2. Seat it in the lane template `~/.temperance_engine/state/lane-templates-from-live.json` using the
   sqlite form `provider/model` (not the UI form).
3. Dry-run: `python3 ~/.agents/skills/temperance-parallel-dispatch/scripts/sync-provider-fleet.py`.
   Read the planned seat changes and the `errored_providers` list.
4. Apply: the same command with `--apply`.
5. Readback: `sqlite3 -readonly ~/.omniroute/storage.sqlite "SELECT name, json_extract(data,'$.models[0]') FROM combos WHERE name LIKE 'noesis-%' ORDER BY name;"`
   and `curl -s -H "Authorization: Bearer $OMNIROUTE_API_KEY" http://coding-mac:20128/v1/models | grep -c noesis-`.
6. Add the row to the instance's provider roster (`snow-gloves-ops/docs/fleet/PROVIDERS.md`).

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

Claude Code also wants `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` and `ANTHROPIC_MODEL=noesis-orchestrator` in its `env`, plus
`"model": "noesis-orchestrator"`, so combo names resolve without an unknown-model warning; `gateway_client.py` does not write these yet.
Over SSH the login Keychain is locked, so `keychain:` refs only resolve in a GUI session; for SSH-only use pass an `env:VAR` ref instead.

Codex keeps whatever default provider it had (for most people the native ChatGPT login). The fleet gateway is then
reachable per run with `codex -c 'model_provider="omniroute"' -m noesis-fast …` or a profile. Pass `--set-default-provider`
to `gateway_client.py set-url` only on a machine whose shell exports the provider's `env_key` (the Coding Mac does).

## Handoff to the Coding Mac

What the Coding Mac needs before anything else: macOS signed in, Remote Login (SSH) and Remote Management on,
Homebrew and node installed. OmniRoute itself is an npm global package (`npm install -g omniroute@<version>`);
the kit records the authoring seat's version so the host can match it.

1. Authoring seat: `bash scripts/fleet/gateway_kit.sh export` with `SNOWGLOVES_DATA` pointing at the private data
   checkout (add `--bind-ip <ip>` when the Coding Mac's Tailscale or LAN address is known). The kit holds the
   instance's `fleet.yaml` and `nodes/`, a `host/` folder (lane template,
   phase combo core, the LaunchAgent plist with secret-shaped values replaced by `REDACTED` and the bind host
   replaced by `${TAILSCALE_IP}`, `providers.txt`, `omniroute-version.txt`), `client-templates/` and
   `README-IMPORT.md`. A leak guard aborts the export if anything secret-shaped is staged.
2. Move it: `scp dist/fleet/gateway-kit-*.tar.gz coding-mac:~/` (an SSH alias for the Coding Mac: its LAN
   name before Tailscale, its Tailscale name after) or Taildrop once the tailnet is up.
3. Coding Mac, over SSH or Screen Sharing as the wing operator user: `verify <tar>`, then `import <tar>` (dry-run, read
   it), then `import <tar> --apply --bind-ip <ip>`. Use the LAN address from `ipconfig getifaddr en0` until
   Tailscale is installed, then re-run with the Tailscale IP. Import installs or aligns OmniRoute, writes a fresh
   storage key, renders and bootstraps the LaunchAgent, seeds the lane template where absent, and prints the
   configuration-transfer options. It never writes a secret.
4. Configuration transfer, by you, over SSH, because providers, combos and keys are secret-bearing and never
   live in the kit:
   - Route A, mirror the seat: copy `~/.omniroute/storage.sqlite` (with `-wal` and `-shm`) and `~/.omniroute/.env`
     from the seat to the Coding Mac, then `launchctl kickstart -k gui/$(id -u)/com.temperance.engine.omniroute`.
     Exact copy of providers, combos and keys. Carry over only sign-ins the operator is entitled to use on the new host.
   - Route B, bundle: on the seat `omniroute sync bundle gw.json --include settings,combos,policies,providers,keys`,
     `scp` it, `omniroute sync import --dry-run gw.json`, then import, then `rm -P gw.json`. `sync bundle` needs a
     CLI key whose scope allows it.
   The Temperance fleet sync script only addresses `127.0.0.1:20128`, so it runs on the gateway host, not remotely.
5. Sign-in checklist on the Coding Mac, for the provider accounts the operator is entitled to use on this host and
   for anything route A did not carry or that a provider re-challenges: Claude Code `claude` then `/login`;
   `codex login`; `grok`; Cursor.app; then in the OmniRoute dashboard re-test those connections, rotate the
   dashboard password (`omniroute reset-password`) and mint the scoped keys (one per wing, one per person).
6. Point each client with `gateway_client.py set-url --host <coding-mac LAN name>.local` before Tailscale
   (`--host coding-mac` once Tailscale resolves it) and confirm with `status`; `fleet.yaml` carries both as
   `gateway.lan_url` and `gateway.url`.

## Health checks

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://coding-mac:20128/healthz        # 200
curl -s -o /dev/null -w '%{http_code}\n' http://coding-mac:20128/v1/models      # 401 without a key is healthy
curl -s -H "Authorization: Bearer $OMNIROUTE_API_KEY" http://coding-mac:20128/v1/models | grep -c noesis-   # > 0
lsof -nP -iTCP:20128 -sTCP:LISTEN                                                 # on the host: <tailscale-ip>:20128
```

## Operator steps outside this repo

These touch `~/.temperance_engine` or the machines themselves and are not done by any script here.

1. Record the gateway's bind address and provider set in the instance's decisions log before changing
   `OMNIROUTE_SERVER_HOST` (a human-gated change on the host).
2. Rotate the OmniRoute dashboard password on the Coding Mac (`omniroute reset-password`).
3. Give the `omniroute` MCP its own key minted with the `mcp-connect` scope, stored under Keychain service
   `temperance-mcp-connect`, per `~/.temperance_engine/docs/operations/omniroute-mcp-key-rotation.md`.
4. Install Tailscale on the authoring seat and join the company tailnet.
5. Keep the `fleet.yaml` host comment accurate (loopback is not bound once the gateway listens on the tailnet address).
6. Add the Tailscale ACL for tcp/20128.

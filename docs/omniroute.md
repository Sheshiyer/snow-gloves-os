# OmniRoute with Claude Code and Codex

Claude and Codex keep their native login and models. OmniRoute is an **opt-in** per session, so `/model`
lists your OmniRoute combos (`noesis-*`, `temperance-coding`) instead of replacing the provider globally.
The gateway key lives only in macOS Keychain (service `OmniRoute Combos Key`) and is read at request time.

```bash
python3 scripts/wire_omniroute.py --status          # what is wired
python3 scripts/wire_omniroute.py                   # dry run: diff of what --apply would change
python3 scripts/wire_omniroute.py --apply           # strip global overrides, add the opt-in layers
python3 scripts/wire_omniroute.py --refresh         # rebuild the Codex combo catalog after combos change
python3 scripts/wire_omniroute.py --rollback        # restore the original configs from .wire-bak.* copies
```

## Use it

| Want | Run | Then |
|---|---|---|
| Claude Code on OmniRoute | `claude-or` | `/model` lists the combos |
| Codex on OmniRoute | `codex-or` (same as `codex --profile omniroute`) | `/model` lists the combos |
| One project always on OmniRoute (Claude) | `python3 scripts/wire_omniroute.py --project PATH` | undo with `--remove` |
| Plain native | `claude` / `codex` | unchanged |

`--apply` does not touch your skills, hooks, plugins, or MCP servers. Claude gets an extra settings
layer (`~/.claude/omniroute.settings.json`, passed with `claude --settings`); Codex gets a profile file
(`~/.codex/omniroute.config.toml`, the Codex 0.160 profile layout) and a generated catalog
(`~/.codex/omniroute-models.json`). OmniRoute's built-in `auto/*` virtual combos are left out of the Codex
catalog; add `--include-auto` to list them.

## The key

1. In the OmniRoute dashboard (`omniroute open keys`), create an API key and set its **catalog scope** to
   **Combos**. Then `/v1/models` returns only combos instead of ~4,500 provider models.
2. `printf '%s\n' "$KEY" | python3 scripts/wire_omniroute.py --store-key`, then `--refresh`.
3. Never put the key in `settings.json`, `config.toml`, or `[shell_environment_policy.set]`.

## Other Macs (Tailscale)

The gateway listens on `127.0.0.1` only. To reach it from another Mac, publish it to the tailnet with
`tailscale serve` rather than rebinding to `0.0.0.0`, then on that Mac run the script with
`--base-url https://<this-mac>.<tailnet>.ts.net:20128` and its own combos-scoped key in its own Keychain.

## Known limits

- One model list per session: an opt-in session shows combos only, a native session shows native models only.
- Codex 0.160 has no per-project profile selector; use `codex-or` from the project folder.
- The desktop apps read the same config files as the CLIs. Whether each app exposes a way to launch with a
  layer or profile has not been verified; the CLIs are the supported path today.

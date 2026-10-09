# Runtime adapters

Snow Gloves is agent-agnostic. The founder picks the runtime (or several), and an adapter tells Snow Gloves how that runtime works: where it keeps skills, MCP servers, rules, and plugins; what file formats it reads; which tool it uses to ask the user a question; and how to enter plan mode.

Each adapter is one file, `adapters/<id>/adapter.yaml`, with schema `snowgloves.adapter.v1`. The loader and renderer are in `scripts/lib/adapters.py`; `scripts/onboard.py --prompt` and `--render-adapter` use them; `scripts/build_catalog.py` copies every adapter into `catalog/modules.json` so the dashboard can show them.

## Shipped adapters

| id | Runtime | Question tool | Skills path | MCP file (format) | Rules |
|---|---|---|---|---|---|
| `hermes` | Hermes Agent (NousResearch) | `clarify` | `~/.hermes/skills` | `~/.hermes/config.yaml` (yaml) | `{project}/AGENTS.md` block |
| `claude` | Claude Code | `AskUserQuestion` | `~/.claude/skills` | `{project}/.mcp.json` (json) | `{project}/CLAUDE.md` block |
| `codex` | OpenAI Codex CLI | `request_user_input` | `~/.codex/skills` | `~/.codex/config.toml` (toml) | `{project}/AGENTS.md` block |
| `cursor` | Cursor | `AskQuestion` | `~/.cursor/skills` | `{project}/.cursor/mcp.json` (json) | `{project}/.cursor/rules/snowgloves.mdc` |
| `opencode` | OpenCode | `question` | `~/.config/opencode/skills` | `~/.config/opencode/opencode.json` (opencode-json) | `{project}/AGENTS.md` block |
| `grok` | Grok CLI | `ask_user_question` | `~/.grok/skills` | `~/.grok/config.toml` (toml) | `{project}/AGENTS.md` block |
| `openclaw` | OpenClaw | `numbered-list` | `~/.openclaw/skills` | `~/.openclaw/openclaw.json` (json) | `~/.openclaw/workspace/AGENTS.md` block |
| `muse` | Muse (placeholder) | `numbered-list` | `~/.muse/skills` | `~/.muse/mcp.json` (json) | `{project}/AGENTS.md` block |
| `generic` | Any agent | `numbered-list` | `{tenant}/runtime/generic/skills` | `{tenant}/runtime/generic/mcp.json` (json) | `{tenant}/runtime/generic/AGENTS.md` block |

`numbered-list` means the runtime has no known question tool; the interview prints numbered options and reads back the answer. `generic` renders everything inside the tenant folder so you can copy it into any runtime.

## Unverified fields

Fields that nobody has confirmed against the real runtime are listed under `verify:`. Every render prints them as a note and records them in `tenants/<slug>/runtime/<runtime>/render.json`. Confirm a field against the runtime's docs or a real install, then delete its `verify` entry.

| Adapter | Fields marked `verify: true` | Notes |
|---|---|---|
| `hermes` | `paths.rules`, `paths.plugins`, `install.1` | |
| `claude` | `plugin_install` | |
| `codex` | `plan_mode`, `paths.skills` | Codex `/plan` and plan-only `request_user_input` are unconfirmed |
| `cursor` | `paths.plugins`, `plugin_install` | |
| `opencode` | `question_tool`, `plugin_install` | |
| `grok` | `homepage`, `paths.plugins` | |
| `openclaw` | `homepage`, `question_tool`, `plan_mode`, `paths.mcp`, `paths.rules`, `plugin_install` | Question tool and plan mode unconfirmed |
| `muse` | `homepage`, `question_tool`, `plan_mode`, `paths.skills`, `paths.mcp`, `paths.rules`, `formats.mcp` | A guess throughout; no Muse CLI was available. Do not use `--write` until confirmed |
| `generic` | none | Writes only inside the tenant folder |

## Adapter fields

```yaml
schema: snowgloves.adapter.v1
id: myruntime                 # must equal the folder name
name: My Runtime
homepage: https://example.com # or null
question_tool: ask_user       # tool name, or numbered-list if none
plan_mode: "How to enter plan mode, in one sentence." # or null
paths:                        # every key required; null if the runtime has none
  skills: "{home}/.myruntime/skills"      # <id>/SKILL.md is written under this
  mcp: "{project}/.myruntime/mcp.json"
  rules: "{project}/AGENTS.md"
  plugins: null
formats:
  skill: skill-md             # skill-md | hermes-skill-md
  mcp: json                   # json | opencode-json | toml | yaml
  mcp_key: mcpServers         # top-level key (or dotted path) holding servers
  rules: markdown-block       # markdown-block | mdc
install:                      # human-readable install commands (list, may be empty)
  - "myruntime mcp add <id> -- <command>"
plugin_install: null          # template with {id} and {repo}, or null
notes: |
  Anything a maintainer should know.
verify:                       # optional; true = whole file unconfirmed, or field -> true
  plan_mode: true
```

Path templates:

- `{home}` is the user's home directory.
- `{project}` is the founder's project folder: `--project`, else `preferences.project` in `tenants/<slug>/runtime.yaml`, else the tenant folder.
- `{tenant}` is `tenants/<slug>/`.

With `--out DIR`, all three roots are redirected under `DIR/` so you can inspect a render without touching real config.

## How a render writes files

`python3 scripts/onboard.py --render-adapter <runtime> --tenant <slug>` is a dry run. Add `--write` to write.

- `skills` and `playbook` cards become `<skills>/<id>/SKILL.md`.
- `mcp` and `connector` cards become MCP entries. JSON files are merged; TOML tables are appended only if missing; YAML config gets a sibling `<name>.snowgloves.yaml` fragment instead of being rewritten. Unparseable JSON also gets a fragment.
- `plugin` cards become install instructions in `tenants/<slug>/runtime/<runtime>/plugins.md`. Snow Gloves never installs plugins itself.
- `pointer` cards and G-Stack connectors are skipped (nothing to install).
- Rules go in a `<!-- snowgloves:start -->` … `<!-- snowgloves:end -->` block; the rest of the file is left alone. `mdc` rules own their whole file.
- `render.json` lists every file written, everything skipped, and the unverified fields.

## Adding a runtime

1. Create `adapters/<id>/adapter.yaml` from the template above. Start from the closest existing adapter.
2. Mark every field you have not confirmed against the runtime under `verify:`. If you are guessing everything, use `verify: true`.
3. If the runtime is new to the catalog, add its id to the allowed `runtimes` values in `scripts/build_catalog.py` and `catalog/SCHEMA.md` so cards can target it.
4. Rebuild and test:

   ```bash
   make catalog
   python3 -m pytest -q tests/test_adapters.py
   python3 scripts/onboard.py --prompt <id>                                   # read the interview
   python3 scripts/onboard.py --render-adapter <id> --tenant acme --out /tmp/sg-render
   ```

5. Inspect `/tmp/sg-render/` and `render.json`. Only render for real with `--write` after the paths are confirmed.

`tests/test_adapters.py` validates every runtime in its `EXPECTED` set against the schema and checks that each `verify` key names a real field. Add your id to `EXPECTED` so CI covers it.

Opting a runtime into OmniRoute without replacing its provider is covered in [omniroute.md](omniroute.md).

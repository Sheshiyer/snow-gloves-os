# Onboarding

Onboarding turns a project the founder has been building into a Snow Gloves tenant. It runs as a **plan-mode interview** inside whatever agent runtime the founder already uses, then a few deterministic commands apply the result.

The interview prompt is `prompts/onboard-interview.md`. The skill that drives it is `skills/sg-onboard/`. The commands are in `scripts/onboard.py` (`scripts/onboarding.sh` is a thin wrapper around it). `python3 scripts/onboard.py --steps` prints the short version of this page.

## The four steps

```bash
# 1. Interview: print the prompt for your runtime and paste it into that runtime, in the founder's project
make onboard-prompt R=claude                  # same as: python3 scripts/onboard.py --prompt claude

# 2. Apply the harvest the interview wrote
python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant acme

# 3. Adjust later
python3 scripts/onboard.py --list --category skills
python3 scripts/onboard.py --enable ms-copywriting,ms-emails --tenant acme

# 4. Render into the runtime: dry run first, then write
python3 scripts/onboard.py --render-adapter claude --tenant acme
python3 scripts/onboard.py --render-adapter claude --tenant acme --write
```

Runtimes: `hermes`, `claude`, `codex`, `cursor`, `opencode`, `grok`, `openclaw`, `muse`, `generic`. See [adapters.md](./adapters.md) for what each one writes and which fields are unconfirmed.

## Step 1: the plan-mode interview

`--prompt <runtime>` fills the template with the runtime's name, how to enter plan mode, its question tool, and the current option lists from `catalog/modules.json`. The agent must:

1. **Enter plan mode first** and stay in it until the file is written. No edits, installs, or enables during the interview. For runtimes with no plan mode (`hermes`, `openclaw`, `muse`) the agent is told not to write files until the interview ends.
2. **Ask one decision at a time** with the runtime's question tool (`AskUserQuestion`, `AskQuestion`, `request_user_input`, `question`, `ask_user_question`, `clarify`), or a numbered list if there is none. It waits for each answer.
3. **Offer only listed ids.** Options come from `modules.json`. `hold` and `refuse` items are never offered; if the founder names one, the agent says it can't be enabled and why.
4. **Never guess.** A missing fact is written as `FILL: <what is missing>`, and the agent asks for it. A `FILL:` line is not a fact.
5. **Quote sources.** Facts come from the repo or the founder's answers, with the file they came from.
6. **Recommend small.** One agent and the one skill the first job needs beat a long list.

Question order: tenant (name + slug), owner, company/customer/offer (gaps only), voice, agents, skills per agent (`add` first, `pointer` second), connectors (with risk and approval shown; high-risk and write connectors need an explicit yes), runtimes (and which is primary), preferences, sources.

The only file the interview writes is `snowgloves-harvest.md` in the founder's project, with these headings in order: `Tenant`, `Owner`, `Company`, `Customer`, `Offer`, `Voice`, `Proof`, `Agents`, `Skills`, `Connectors`, `Runtimes`, `Preferences`, `Sources`, `Open questions`. List sections use `- id` or `- id: reason` lines, or `- none`. `Preferences` must include `approval_mode:` (`always-ask`, `ask-on-write`, or `ask-on-send`), `render:` (`dry-run` or `write`), and `project:` (the absolute path of the founder's project).

## `FILL:` behaviour

`FILL:` marks a fact the interview could not establish. The pipeline carries it through and never treats it as data:

| Where | What happens to `FILL:` |
|---|---|
| List sections (agents, skills, connectors, runtimes, sources) | `FILL` lines are skipped; they never become an enabled id |
| `Tenant` slug | A `FILL` slug is ignored and `--tenant` wins; a real slug that differs from `--tenant` is an error |
| `Tenant` name | A `FILL` name falls back to the slug |
| Context sections (owner, company, customer, offer, voice, proof) | Written as-is to `tenants/<slug>/context/<section>.md`; an empty section becomes `FILL: the harvest left <section> blank.` |
| Anywhere in the file | Every `FILL:` line is collected into `context/open-questions.md` (unless the harvest's own `Open questions` section is filled in) and counted in the command output |
| `preferences.project` | A `FILL` value is ignored; `{project}` falls back to `--project` or the tenant folder |
| MCP entries | If a rendered MCP entry still contains `FILL:`, the render warns that a launch command must be added before starting the runtime |

To close a `FILL:`, edit the harvest and re-run `--apply-harvest`, or edit the context file directly.

## Step 2: apply

`--apply-harvest` validates every chosen id and runtime **before** writing anything, then writes:

- `tenants/<slug>/` (created like `scripts/tenant_new.sh` if missing, and registered in `tenants/_registry.yaml`)
- `context/{owner,company,customer,offer,voice,proof}.md` and `context/open-questions.md`
- `raw/harvest.md` (a copy of the harvest)
- `enabled.yaml` (schema `snowgloves.enabled.v1`): the enabled modules and agents
- `runtime.yaml` (schema `snowgloves.runtime.v1`): runtimes, the primary one, and preferences
- `sources.yaml` if it doesn't exist yet (an existing one is left alone and new paths are reported)

## Step 3: adjust

`--list [--category <c>] [--json]` shows the catalog. `--enable id,id --tenant <slug>` adds to `enabled.yaml` (use `--replace` to start over). Only `add` and `pointer` ids are accepted. Previously enabled ids are re-checked, so a card that has since moved to `hold` drops out with a message.

## Step 4: render

`--render-adapter <runtime> --tenant <slug>` shows what would be written for that runtime. `--write` writes it. `--out DIR` renders under a scratch folder instead of real paths, and `--project DIR` overrides `{project}`. After a write, `tenants/<slug>/runtime/<runtime>/render.json` lists every file written, everything skipped, and the adapter fields still marked `verify`.

Load `skills/connector-gate` before any external tool call; it reads `tenants/<slug>/enabled.yaml` and refuses connectors the tenant has not enabled.

## Legacy flow

`make onboard` (or `bash scripts/onboarding.sh` with no arguments) still runs the original interactive tenant + sources prompt (`scripts/onboard.py --init-tenant`). Any arguments passed to `scripts/onboarding.sh` go straight to `scripts/onboard.py`.

## Dashboard

The Tauri app in `apps/onboarding/` adds a guided onboarding flow and a Modules dashboard over the same `modules.json` and `enabled.yaml`. The static version is at https://sheshiyer.github.io/snow-gloves-os/.

# Claude Code mods

A Claude Code **mod** is a plugin whose hooks module runs inside Claude Code: TypeScript event handlers that can watch, rewrite, or answer a tool call, a prompt, a turn, or a part of the screen, and that can draw panes and a band above the prompt. Snow Gloves ships its own mods in `mods/`, gates third-party mods through the catalog, and keeps the platform's rules in Python so the mods stay thin.

Official docs: [overview](https://code.claude.com/docs/en/plugins/mods/overview), [create](https://code.claude.com/docs/en/plugins/mods/create), [interface](https://code.claude.com/docs/en/plugins/mods/interface), [events](https://code.claude.com/docs/en/plugins/mods/events), [API](https://code.claude.com/docs/en/plugins/mods/api), [test](https://code.claude.com/docs/en/plugins/mods/test), [admin](https://code.claude.com/docs/en/plugins/mods/admin), [reference](https://code.claude.com/docs/en/plugins/mods/reference). The types Claude Code writes into a mod's `.claude-plugin/types/` are the final word for your build.

## What a mod can do, and what it costs

| | Mod | Settings hook | Skill | MCP server |
|---|---|---|---|---|
| Runs | inside Claude Code | as a process Claude Code starts | as text Claude reads | as a process or service |
| Can draw | panes, the band, toasts, status lines; restyle tool rows and the spinner | no | no | no |
| Can change | tool calls, prompts, turns, commands, subagents | allow, block, or rewrite a call or prompt | what Claude knows | which tools Claude has |

Mods are **not sandboxed**. A mod runs with the user's permissions, sees every prompt and tool call, and can approve a tool call before the user is asked. That is why Snow Gloves treats a third-party mod like any other catalog card: it starts at `hold` and needs a review.

Hooks for one event form a middleware chain, `($, e, next)`. The order is: managed settings `PreToolUse` hooks, then `prependPlugins`, then mods the user installed, then `appendPlugins`, then built-in mods, then Claude Code's own behavior. **Every other `PreToolUse` settings hook runs after the last mod calls `next`**, so a mod that answers a call itself, without `next`, silently skips those hooks. Snow Gloves' own mods never do (rule I2 below), because `~/.claude/hooks/erp-read-only.py` is one of those hooks.

Versions: mods need Claude Code 2.1.287 or later in the terminal; the Desktop app's Code tab bundles its own copy. Snow Gloves mods use only 2.1.287 APIs (no `ui.fault`, `isDeferred`, prompt block arrays, or `mock.session`).

## The community directory: claudemod.com

[claudemod.com](https://www.claudemod.com/) is a community-run index (not affiliated with Anthropic) of about 170 entries: mods, skills, MCP servers, commands, agents, hooks, plugins, and configs. Its mod gallery shows the patterns that matter for Snow Gloves:

| Pattern | Examples on claudemod.com | Snow Gloves equivalent |
|---|---|---|
| Pinned status above the prompt | GitHub CI Status, PR Tracker, Burn Meter | `sg-rail` |
| Tool guard with confirmation | Launch Codes, Secret Redactor | `sg-connector-gate`, idea 9 `sg-guard` |
| Pane beside the transcript | Terminal Browser, Flightdeck | `sg-approvals`, ideas 4, 7 |
| Agent and cost dashboards | Agent Flow, cctop, Claude Statuspane | ideas 5, 6 |

None of them is enabled here. To consider one, run the intake in idea 10: it records the mod's `claude plugin validate --json` report in a `hold` card for the founder to review.

## Where Snow Gloves stood before this

- No mods. The "custom mods" were classic settings hooks in `~/.claude/settings.json`: Temperance `PromptProcessing.hook.ts` (UserPromptSubmit), `ISASync` and `CheckpointPerISC` (PostToolUse), and `erp-read-only.py`, a fail-closed PreToolUse guard on the ERP connector.
- The Temperance "Dynamic Island" status line was built but never wired, and its rail, the Manifest runtime receipt, and the PAI mode offer rode along in Claude's context on every prompt.
- `skills/connector-gate` was a procedure Claude was asked to follow, not something enforced.
- The Claude adapter rendered skills, MCP config, and rules; plugins became an instruction list.

## Design

### Python owns the rules; mods are thin shells

A hooks module has no Node APIs, no YAML parser, and can import only files inside its own plugin, and `$` cannot be passed to an imported function. So the platform's semantics stay in Python and each mod calls one CLI through `$.process.run`:

| `scripts/sg_mods.py` | Prints | Used by |
|---|---|---|
| `snapshot [--data-root] [--tenant] [--cwd]` | `snowgloves.mods-snapshot.v1`: data root and where it came from, the tenant and how it was resolved, pending approvals (payload **keys** only), graph-walk verdict, ISA progress, Hermes and OmniRoute endpoints, warnings | sg-rail, sg-approvals |
| `gate-table --tenant [--ttl-hours]` | `snowgloves.mods-gate.v1`: every catalog-managed MCP or connector card with its disposition, risk, approval flag and whether the tenant enabled it, plus approved grants within the TTL and pending tickets | sg-connector-gate |
| `request-approval --tenant --connector --capability [--tool]` | the queued ticket, or the pending one it matches | sg-connector-gate |

The tenant is the `--tenant` flag (`SNOWGLOVES_TENANT` or the mod's `tenant` option), else the registered tenant whose `runtime.yaml` `preferences.project` holds the working directory. It never falls back to `_demo`. Approvals are decided by the existing `scripts/approvals.py approve|reject --actor` (now with `--data-root`). Tests: `tests/test_sg_mods.py`.

The mods find the platform at `$.plugin.root/../..` (override: `platformRoot`) and run `<platform>/.venv/bin/python` when it exists, else `python3`.

### Layout

```text
mods/
├── .claude-plugin/marketplace.json      # the snowgloves-mods directory marketplace
└── sg-<name>/
    ├── .claude-plugin/plugin.json      # manifest + userConfig (tenant, dataRoot, platformRoot, ...)
    ├── hooks/hooks.json                # { "modules": ["./register.tsx"] }
    ├── hooks/register.tsx              # every $ call lives here, in top-level functions
    ├── hooks/lib.ts                    # pure helpers, no $; imported by register and tests
    ├── types/index.d.ts                # PluginState for $.state, and shared types
    └── tests/*.test.ts                 # claude plugin test
```

### Catalog and adapter

- Catalog category `mod` (`catalog/SCHEMA.md`). First-party `sg-*` cards are `add`. A third-party mod starts at `hold`, and its card body records the `hooks:` and `calls:` from `claude plugin validate --json`.
- The Claude adapter has `paths.mods: "{platform}/mods"` and `formats.mods: claude-plugin-settings`. `scripts/onboard.py --render-adapter claude --tenant <t>` writes `tenants/<t>/runtime/claude/mods.settings.json`, a fragment with `extraKnownMarketplaces` (the directory marketplace), `enabledPlugins`, and `pluginConfigs` (each mod's `tenant` and `dataRoot` options). It never edits `~/.claude/settings.json`; `plugins.md` says how to merge it or install with `claude plugin install`. Other runtimes skip mod cards with "no mod support".
- A directory marketplace loads its plugins in place, so a `git pull` of the platform updates the mods.

### Rules every Snow Gloves mod follows

`make mods-check` enforces them with `scripts/check_mod_invariants.py` (source checks plus a per-mod allowlist of the `calls:` that `claude plugin validate --json` reports).

| Rule | What | Why |
|---|---|---|
| I1 | No `tool.check` hook and never `decision: 'allow'` | A user mod's allow overrides `ask` rules and non-managed `PreToolUse` blocks |
| I2 | A `tool.call` hook returns `next(e)` or `{ deny }`, never `{ result }` | Answering a call skips every non-managed `PreToolUse` hook, including `erp-read-only.py` |
| I3 | No `$.tool.register`, no `$.prompt.submit`, no `asUser` | Decisions (approvals) stay with a person; the model can't press a mod's button |
| I4 | Every `tool.call` hook is registered as `on('tool.call', matcher, fn).catch(...)` and fails closed for the servers it manages only | A failed guard must not let a managed call through, nor block someone else's server |
| I5 | `$.http.fetch` only in mods that probe the platform's own endpoints (`config/snowgloves.yaml`, the fleet gateway) | No mod talks to the open internet |
| I6 | No `$.fs.write`, no `$.process.spawn` | Mutations go through the platform's CLIs, which keep their own audit trail |

## The three mods that ship now

| Mod | Surface | What it does |
|---|---|---|
| `sg-rail` | band above the prompt, `/sg` | Every 30 s: snapshot + `/healthz` probes. Line 1: `SG <tenant> · data <ops\|fixtures> · hermes ● · omniroute ● · approvals N · walk GREEN · ISA 0/20`. Lines 2 and 3: the Temperance rail and Manifest status (below). Buttons: `approvals`, `hide`. `/sg` prints the same as text, so it also works in `claude -p` and VS Code; `/sg hide\|show` toggles the band. |
| `sg-connector-gate` | `tool.call` guard on `mcp__*`, `/sg-gate` | `skills/connector-gate` as code. For a catalog-managed server: `hold`/`refuse` never run; a server the tenant hasn't enabled is refused with the `onboard.py --enable` command; a high-risk or `approval: yes` tool without a grant queues a ticket and is refused until a person approves it. Unmanaged servers (the claude.ai connectors, ERP) go on untouched. No tenant, or `gateMode: observe`: it only logs. |
| `sg-approvals` | pane, toast, `/approvals` | The review desk. Pending tickets across tenants, payload keys only. `approve` and `reject` are buttons only a person can press; a high-risk approval asks first. Decides through `approvals.py --actor`. A 30 s timer toasts new tickets and never opens the pane by itself. In `claude -p` it answers in text. |

### Try them

```bash
make mods-dev T=_demo
```

That starts `claude` with every mod loaded from its folder (`--plugin-dir`, hot-reloaded on save). To keep them, render the settings fragment for a tenant, or install from the marketplace:

```bash
python3 scripts/onboard.py --render-adapter claude --tenant <slug> --write
```

```bash
claude plugin marketplace add ./mods
```

Then `claude plugin install sg-rail@snowgloves-mods` (and the others), and `/reload-plugins` in an open session. In the Desktop app, use `/plugin` in a Code-tab session.

### The Temperance rail moves to the band

While `sg-rail` is loaded it sets `TEMPERANCE_RAIL_SINK=file`. Temperance `PromptProcessing.hook.ts` then:

- writes the full rail, the Manifest runtime receipt, and the PAI mode offer to `~/.claude/MEMORY/STATE/rail/<session>.ui.json` (`temperance.rail-ui.v1`, written atomically), which the band draws;
- keeps in Claude's context the classifier block, the gsd rail, and a compact rail: the header with combo and workers, then `CONTRACT` and `DISPATCH`, which are instructions Claude needs.

Measured on one prompt: 2,450 characters of context before, 1,251 after. The PAI mode offer (which tells the agent to open a ChatGPT in-app browser) no longer reaches Claude. With the mod off, or under `--safe-mode`, the variable is unset and the envelope is exactly as before. The hook source is `~/.temperance_engine/hooks/claude/PromptProcessing.hook.ts`, copied to `~/.claude/hooks/`; both have `*.bak-20261010` backups.

## Ten implementation ideas

Ideas 1 to 3 are the shipped mods above. Each of 4 to 10 is specified enough to build: surface, hooks and API, data, behavior, failure modes, tests, and what it depends on. All of them follow rules I1 to I6, add a `sg_mods.py` subcommand when they need platform data, and add their allowlist to `scripts/check_mod_invariants.py`.

### 1. sg-rail: status band (shipped)

See above. Next steps: a second band line for `$.session.usage()` (context %, plan limits) once idea 6 lands, and a `/sg tenant <slug>` picker that writes the `tenant` option through `$.config.set`.

### 2. sg-connector-gate: connector-gate as code (shipped)

Next steps: a `tool.describe` hook that appends "not enabled for <tenant>" to a managed tool's description and sets `isDeferred: true` (Claude Code 2.1.293+), so Claude stops reaching for tools it can't use; and per-capability grants (`capability: "*"`) once the founder wants day passes.

### 3. sg-approvals: review desk (shipped)

Next steps: a payload preview that `sg_mods.py` redacts through `scripts/lib/redact.py` instead of showing keys only; a reason `Input` on reject; and a graph-hook-diff view for tickets from `graph_upgrade.py` (`kind: graph-hook-diff`), showing the proposed `skill-hooks.yaml` change.

### 4. sg-hermes: event stream, route lens, replay

- **Surface:** `/hermes` pane with three tabs (buttons with hotkeys `1` `2` `3`), as in the docs' `hello-tabs` pattern.
- **Live tab:** `$.clock.every(5000)` fetches `GET :4100/events` and keeps the newest 200 in `$.state`. `/events` ignores `?since=` today, so the mod diffs by `ts`; **prerequisite**: implement `since` in `scripts/hermes.py` (a 10-line filter plus a test) and switch to it.
- **Route tab:** an `Input` posts the typed task title to `POST :4100/test/e2e` and shows each route: agent, hook, skills, `matched_glob`, constraint, escalation. This puts the `route()` function in front of whoever is editing `workflows/skill-hooks.yaml`.
- **Replay tab:** a button runs `scripts/replay.py --last 20` (read-only) and lists the events whose route `changed`.
- **Telemetry publisher (opt-in `publishTurns`):** `turn.complete` posts `{channel, event: {kind: 'claude.turn', session, durationMs, usage, tenant}}` to `/publish`. This is the first real traffic Hermes gets from Claude sessions, so `sentinel_sweep.py` has something to measure and the per-agent "heartbeat" in `agents/*/HEARTBEAT.md` has a data source.
- **Failure modes:** Hermes down → the pane says so and the band (idea 1) already shows `hermes ○`; a publish failure is dropped, never retried in a hook.
- **Tests:** stub `http.fetch` for `/events` and `/test/e2e`; mount the pane on both surfaces; `mock.clock` for polling; check `turn.complete` posts only with the option on.
- **Allowlist adds:** `$.http.fetch` (I5: Hermes URL from the snapshot only).

### 5. sg-org: the seven agents as Claude subagent types

- **Surface:** subagent types `sg-org:ceo`, `sg-org:cto`, `sg-org:chief-of-staff`, `sg-org:librarian`, `sg-org:interpreter`, `sg-org:dispatcher`, `sg-org:sentinel`, plus an `/org` pane.
- **Hooks and API:** `session.start` calls `$.agent.register` once per agent. `prompt` is built by a new `sg_mods.py agents` subcommand from `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, and the default skill in `skills/registry.yaml`. `tools` comes from `TOOLS.md`; sentinel and librarian get read-only tools. `agent.offer` withholds roles not in the tenant's `enabled.yaml` `agents:`. `agent.spawn` sets `model` per role from a role → combo map (for example sentinel → `noesis-verify`) only when `ANTHROPIC_BASE_URL` points at OmniRoute.
- **Pane:** one lane per agent: default skill, hook ids from `skill-hooks.yaml`, last routed event (from idea 4's feed), and the CoS → CTO → CEO escalation chain. Heartbeats are not implemented in the platform, so the lane says `stale` rather than pretending.
- **Failure modes:** a missing agent file skips that agent with a log line; `agent.spawn` never refuses, it only picks a model.
- **Tests:** stub `agent.register` and assert each spec; `agent.offer` withholds an unenabled role; `agent.spawn` leaves the model alone off OmniRoute.

### 6. sg-omniroute: model, cache and budget ledger

- **Surface:** a meter in the band (context %, plan limits) and an `/omniroute` pane with a per-request ledger.
- **Hooks and API:** a `turn.step` async generator does `const result = yield* next(e)` and records `result.usage` (input, output, cache read, cache write) and the model per request, main conversation and subagents (`e.agentId`) separately. `$.session.usage()` feeds the meter. `/combo` fetches `GET :20128/v1/models` and shows the `noesis-*` and `temperance-*` combos; a `Select` sets the role → combo map idea 5 uses.
- **Why:** the Temperance rail promises budgets per combo; this shows what each combo actually costs and how much the prompt cache saves, per session.
- **Safety:** read-only toward OmniRoute. It never reads the key (`apiKeyHelper` stays in the Keychain) and never changes the session's own model.
- **Tests:** a `turn.step` stub that streams and returns usage; check the ledger rows and the cache ratio; `mock.clock` for the meter.

### 7. sg-fleet: fleet cockpit

- **Surface:** `/fleet` pane. In the terminal, a `Raster` heat map, wings (rows) × doctor checks (columns), green/amber/red; on desktop, a text table (no `Raster` there).
- **Hooks and API:** every 2 minutes, `$.process.run` on `scripts/fleet/doctor.py --json` (`snowgloves.fleet-doctor.v1`) and `scripts/fleet/gateway_client.py status` (FLEET or NOT-FLEET per surface). A toast when a `critical` check (node-profile, gateway, tenants) turns red. The pane is never opened unasked.
- **When `feat/hermes-task-graph` lands:** a task board from the fleet coordinator `:4101 /v1/tasks` with the stages plan, reference, review, dispatch, verify, and the infra snapshot from `:18761/api/infra/snapshot`. These are the "fleet map" and "session board" views of `docs/FLEET-CONTROL-PLANE-PLAN.md`, in the terminal first.
- **Tests:** stub both scripts; mount on both surfaces and check the desktop text fallback; `mock.clock` for the toast on a red critical check.

### 8. sg-handoff: transfer dock and attention inbox

- **Surface:** `/handoff <sessionId>` and an `/inbox` pane.
- **Handoff:** `$.model.fork({ prompt })` asks the session's own model for a handoff (goal, state, open questions, next step) using the cached conversation. After `$.ui.ask` confirms, `sg_mods.py write-handoff` writes `.project/HANDOFF.md` (a CLI, per rule I6) and `$.session.send({ to: { sessionId } })` delivers a pointer to it.
- **Inbox:** `session.receive` hooks peer messages. When the user has turned inbox mode on, messages tagged `[sg]` are `consumed` into the pane instead of interrupting the running turn. A "hand to Claude" button submits the message as a turn. That needs `$.prompt.submit` (not `asUser`), so this mod gets a documented exception to rule I3 for that one button.
- **Why:** this is the "transfer dock" of `docs/SESSION-WORLD-DESIGN.md` and the "attention inbox" of the fleet plan, for 40 to 50 sessions across the wings.
- **Failure modes:** an undelivered send shows its reason in a toast; inbox mode off means every message goes straight to Claude as today.
- **Tests:** stub `model.fork`, `session.send`, and `ui.ask`; fire `session.receive` with and without inbox mode.

### 9. sg-guard: ERP and PII defense in depth, and mod supply-chain policy

- **ERP second layer:** a `tool.call` hook on the ERP connector's tools that allows only `execute_read_only_query` with a single `SELECT` that returns ids, and refuses everything else with `{ deny }`. When it allows, it **always** ends in `next(e)`, so `erp-read-only.py` still runs after it (rule I2). Two independent guards, one in-process and one a settings hook.
- **PII redaction:** after `await next(e)` on MCP tools, rewrite the result text with the patterns of `scripts/lib/redact.py`, ported to `lib.ts` with parity tests that run the same fixtures through both.
- **Mod supply-chain policy:** a `plugin.register` hook that refuses a user-tier mod whose `e.uses.calls` include `process.spawn`, or `http.fetch` without a catalog card, unless its catalog card is `add`. This only takes effect when `sg-guard` is in `prependPlugins`, which is read from managed settings, or from user settings only on a machine with no managed settings and no Team or Enterprise sign-in. Test it with `tier('prepend')` in the test kit.
- **Failure modes:** every hook has `.catch` that refuses (fail closed) for its own scope.

### 10. sg-catalog: catalog browser and claudemod.com intake

- **Surface:** `/sg-catalog` pane with `Select` filters (category, disposition, agent) over `catalog/modules.json`, showing which cards the active tenant has enabled.
- **Enable:** a button runs `scripts/onboard.py --tenant <t> --enable <id>` after `$.ui.ask`; `hold` and `refuse` cards show the refusal text and no button.
- **Intake:** `/sg-mod-review <path>` runs `claude plugin validate --json` on a third-party mod folder (for example Secret Redactor or Launch Codes from claudemod.com) and has `sg_mods.py draft-card` write a `hold` card with the hooks, calls, env reads, state, and gating hooks. It flags anything rules I1 to I6 would refuse. The founder reviews the card; nothing installs.
- **Tests:** stub the catalog and `onboard.py`; check that a `hold` card has no enable button; feed a canned validate report into the intake.

## Checks

```bash
make mods-check
```

That runs `claude plugin validate --strict` on the marketplace and each mod, `claude plugin test` in each mod, then `scripts/check_mod_invariants.py --require-claude`. The Python side is in `make test` (`tests/test_sg_mods.py`, `tests/test_check_mod_invariants.py`, and the mod cases in `tests/test_adapters.py`). The opt-in local job `mods` in `.local-jobs/jobs.json` runs `make mods-check`.

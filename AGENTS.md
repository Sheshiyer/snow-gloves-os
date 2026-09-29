# Snow Gloves OS — Agents

| Slug | Role | Layer |
|---|---|---|
| ceo | Chief Executive Agent | Strategy |
| cto | Chief Technology Agent | Architecture |
| chief-of-staff | Skill Orchestrator | Routing |
| librarian | Knowledge + Embeddings | Knowledge |
| interpreter | Interpretation Engine | Interpretation |
| dispatcher | Hermes/Paperclip Bridge | Orchestration |
| sentinel | Audit & Risk | Governance |

Each agent ships **at least 5 .md files**:
`IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `SKILLS.md`, `HEARTBEAT.md`
plus `MANIFEST.yaml`.

## Orchestration model

```
   CEO  <----- strategic escalation -----+
    |                                    |
   CTO  <----- technical escalation ----+|
    |                                   ||
    v                                   ||
[ Chief of Staff (Skill Orchestrator) ] <-- routes skills
    |
    +--> Librarian
    +--> Interpreter
    +--> Dispatcher
    +--> Sentinel
```

Events reach the Chief of Staff through **Hermes** (`scripts/hermes.py`, port 4100).

## Modules and runtimes

- Agents pick up third-party modules only through a tenant's `tenants/<slug>/enabled.yaml`. Options come from `catalog/modules.json` (built from `catalog/cards/` by `scripts/build_catalog.py`); `hold` and `refuse` cards are never enabled. Load `skills/connector-gate` before any external tool call.
- The runtime is the founder's choice. `adapters/<runtime>/adapter.yaml` says where that runtime keeps skills, MCP config, and rules; `scripts/onboard.py --render-adapter` writes them. Onboarding is the plan-mode interview in `skills/sg-onboard/`.
- Docs: `docs/catalog.md`, `docs/adapters.md`, `docs/onboarding.md`.

<!-- temperance:project-rail:start -->
## Temperance project rail

This repository is registered with **Temperance Engine** as a project rail.
Host runtime (models, OmniRoute, OpenCode plugins) lives under `~/.temperance_engine`
and `~/.config/opencode`; this repo owns planning and acceptance.

| Concern | Authority |
|---|---|
| Models / failover / budgets | Host OmniRoute + temperance combos |
| Planning spine | `.planning/` (GSD) + `temperance-next-wave` |
| Acceptance | `ISA.md` when present |
| Handoff (if present) | `.project/HANDOFF.md` |
| Parallel execute | `noesis-execute` / `temperance-batch` |

### Auto next-wave

When an agent session starts in this cwd, enrich injects `dispatch: NEXT-WAVE …`.
**Do not wait** for the user to say "temperance dispatch" or "proceed".

```bash
temperance-next-wave --cwd .
temperance-project-init --cwd . --check
temperance-batch --foreground --tasks .planning/next-wave-tasks.json --concurrency 4 --worktree
```

Manifest: `.temperance/project.json` (schema temperance.project.v1)
<!-- temperance:project-rail:end -->


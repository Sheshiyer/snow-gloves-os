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


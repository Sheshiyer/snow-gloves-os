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

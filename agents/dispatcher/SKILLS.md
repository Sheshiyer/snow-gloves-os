# Skills — Orchestration Dispatcher

## Assigned skills (from snow gloves skill repository)
- inference-sh/agent-skills@viral-campaign-ideator
- inference-sh/agent-skills@referral-program-designer
- inference-sh/agent-skills@business-network-expansion

## Explee cluster (external source: `Sheshiyer/explee-skills@`)
GTM / prospecting / partner-channel intelligence. **Entry point: `explee-orchestrator`** (routes internally to the spokes).
- `explee-orchestrator` — hub / router
- `explee-search` — companies / people / ICP → filters
- `explee-enrichment` — email finding (paid)
- `explee-agents` — agent runs (paid)
- `explee-autogtm` — full GTM pipeline (paid)
- `explee-auth-cookie` — cookie / `EXPLEE_SECRETS` KV auth model
- `explee-api-core` — shared API reference

Calls route through the `explee-proxy` G-Stack connector. Paid ops (`explee.paid_search`,
`explee.enrichment`, `explee.autogtm`) are approval-gated (see `MANIFEST.yaml`). **Brand rule:**
partner / channel intelligence only — never cold individual outreach.

## Routing
Routed via `workflows/skill-hooks.yaml` (Chief of Staff orchestrator).
Hooks for this agent are defined under `routing.dispatcher.hooks`.

## Escalation
Falls back to chief-of-staff; technical issues escalate to cto, strategic to ceo.

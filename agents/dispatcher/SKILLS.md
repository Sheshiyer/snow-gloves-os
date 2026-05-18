# Skills — Orchestration Dispatcher

## Assigned skills (from snow gloves skill repository)
- inference-sh/agent-skills@viral-campaign-ideator
- inference-sh/agent-skills@referral-program-designer
- inference-sh/agent-skills@business-network-expansion

## Routing
Routed via `workflows/skill-hooks.yaml` (Chief of Staff orchestrator).
Hooks for this agent are defined under `routing.dispatcher.hooks`.

## Escalation
Falls back to chief-of-staff; technical issues escalate to cto, strategic to ceo.

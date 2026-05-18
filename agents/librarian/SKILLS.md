# Skills — Knowledge Librarian

## Assigned skills (from snow gloves skill repository)
- inference-sh/agent-skills@audience-segmentation-generator
- inference-sh/agent-skills@unmet-needs-analyzer
- inference-sh/agent-skills@startup-idea-generator
- inference-sh/agent-skills@content-marketing-leadgen

## Routing
Routed via `workflows/skill-hooks.yaml` (Chief of Staff orchestrator).
Hooks for this agent are defined under `routing.librarian.hooks`.

## Escalation
Falls back to chief-of-staff; technical issues escalate to cto, strategic to ceo.

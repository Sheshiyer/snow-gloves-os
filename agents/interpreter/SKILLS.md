# Skills — Interpretation Engine

## Assigned skills (from snow gloves skill repository)
- inference-sh/agent-skills@brand-story-builder
- inference-sh/agent-skills@value-proposition-crafter
- inference-sh/agent-skills@elevator-pitch-generator
- inference-sh/agent-skills@marketing-plan-generator
- inference-sh/agent-skills@headline-generator
- inference-sh/agent-skills@twitter-thread-aida-writer
- inference-sh/agent-skills@newsletter-pas-writer
- inference-sh/agent-skills@open-loop-social-writer
- inference-sh/agent-skills@fomo-copy-generator
- inference-sh/agent-skills@listicle-idea-generator
- inference-sh/agent-skills@engagement-question-writer
- inference-sh/agent-skills@writing-editor-proofreader
- inference-sh/agent-skills@sales-funnel-designer
- inference-sh/agent-skills@product-launch-strategy
- inference-sh/agent-skills@channel-prioritization-planner
- inference-sh/agent-skills@pricing-strategy-optimizer

## Routing
Routed via `workflows/skill-hooks.yaml` (Chief of Staff orchestrator).
Hooks for this agent are defined under `routing.interpreter.hooks`.

## Escalation
Falls back to chief-of-staff; technical issues escalate to cto, strategic to ceo.

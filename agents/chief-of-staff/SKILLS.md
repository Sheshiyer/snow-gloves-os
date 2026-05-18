# Skills — Chief of Staff (Skill Orchestrator)

## Assigned skills (from snow gloves skill repository)
- inference-sh/agent-skills@corporate-communication-coach
- inference-sh/agent-skills@negotiation-skills-coach
- inference-sh/agent-skills@workplace-conflict-resolver
- inference-sh/agent-skills@performance-feedback-writer
- inference-sh/agent-skills@workplace-culture-onboarding
- inference-sh/agent-skills@remote-productivity-coach
- inference-sh/agent-skills@resilience-during-tough-periods
- inference-sh/agent-skills@work-life-balance-planner
- inference-sh/agent-skills@career-advancement-planner
- inference-sh/agent-skills@career-transition-roadmap
- inference-sh/agent-skills@interview-prep-coach
- inference-sh/agent-skills@job-search-strategy
- inference-sh/agent-skills@professional-networking-playbook
- inference-sh/agent-skills@professional-development-curator
- inference-sh/agent-skills@resume-enhancer
- inference-sh/agent-skills@portfolio-builder
- inference-sh/agent-skills@personal-brand-strategy

## Routing
Routed via `workflows/skill-hooks.yaml` (Chief of Staff orchestrator).
Hooks for this agent are defined under `routing.chief-of-staff.hooks`.

## Escalation
Falls back to chief-of-staff; technical issues escalate to cto, strategic to ceo.

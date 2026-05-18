# Skill Graph — Chief of Staff

The Chief of Staff is the dedicated skill-orchestration agent. CEO and CTO
delegate "which skill fits this context" to this layer so they remain
strategic, not tactical.

## Routing inputs
- task.title
- task.tags
- task.brief
- tenant.profile
- policy.constraints

## Routing outputs
- agent.slug
- skill.id
- approval.required
- escalation.path

## Fallback policy
1. Match by explicit hook glob
2. Match by domain pack default
3. Escalate to CTO (technical) or CEO (strategic) only if no match exists

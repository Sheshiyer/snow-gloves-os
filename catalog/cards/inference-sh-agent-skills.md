---
id: inference-sh-agent-skills
name: inference-sh agent-skills pack
category: skills
kind: skill-pack
disposition: add
repo: "https://github.com/inference-sh/agent-skills"
source: "catalog-core-descope"
risk: low
approval: no
agents: [ceo, cto, chief-of-staff, librarian, interpreter, dispatcher, sentinel]
hooks: [ceo.strategy-and-vision, cto.architecture-and-execution, chief-of-staff.people-ops, librarian.research-and-discovery, interpreter.narrative-and-brand, dispatcher.virality-and-distribution, sentinel.investment-and-financial-risk]
runtimes: [any]
summary: "Optional coaching/GTM skill pack. Not core. Enable per tenant; do not vendor into skill-hooks.yaml by default."
---

# inference-sh agent-skills

Optional module. The core graph only routes native `snowgloves:*` skills. This pack is the old default `source_prefix` (mission-vision-refiner, viral-campaign-ideator, and the rest). Enable it when a tenant wants those desks filled; `graph-upgrade` may propose hook diffs, never auto-merge.

## Provenance

- Former core `skills/registry.yaml` `source_prefix: inference-sh/agent-skills@`
- Not cloned into this repo

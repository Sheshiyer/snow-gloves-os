---
id: sg-org
name: "Snow Gloves organisation"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-org"
risk: low
approval: no
agents: [ceo, chief-of-staff]
hooks: []
runtimes: [claude]
summary: "The seven agents as Claude subagent types sg-org:<slug>, and /org."
---

# Snow Gloves organisation

A first-party Claude Code mod at `mods/sg-org`. `scripts/sg_mods.py agents` builds a spec per agent from `agents/<slug>/` and the skill registry; `session.start` registers each as a subagent type. `agent.offer` withholds a role the tenant's `enabled.yaml` does not list (an empty list means no restriction). `agent.spawn` picks a model per role from the `roleCombos` option only when `ANTHROPIC_BASE_URL` points at OmniRoute, and never refuses. `/org` shows a lane per agent; heartbeats are not implemented in the platform, so lanes say `stale`.

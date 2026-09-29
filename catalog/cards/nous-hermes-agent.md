---
id: nous-hermes-agent
name: "NousResearch hermes-agent"
category: plugin
kind: runtime
disposition: refuse
repo: "https://github.com/NousResearch/hermes-agent"
source: "2100625120691720385"
risk: low
approval: no
agents: [dispatcher]
hooks: []
runtimes: [hermes]
summary: "Third-party agent runtime that shares the Hermes name. Not the Snow Gloves Hermes event bus (scripts/hermes.py)."
---

# NousResearch hermes-agent

Four-Signal 4/12. Name collision only; the Dispatcher bridge stays on the native bus. The `hermes` adapter targets the Nous runtime only when a founder picks it as a runtime.

## Provenance

- Source: X bookmark `2100625120691720385` (https://x.com/i/status/2100625120691720385)
- Upstream: https://github.com/NousResearch/hermes-agent
- tenants/_demo/wiki/systems/ecosystem-candidates.md
- tenants/_demo/wiki/systems/skill-hook-crosswalk.md

Pointer card. Nothing here is installed or wired into `workflows/skill-hooks.yaml`.

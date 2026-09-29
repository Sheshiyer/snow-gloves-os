---
id: portless
name: "portless (OAuth local URLs)"
category: connector
kind: skill-pattern
disposition: add
repo: "https://github.com/vercel-labs/portless"
source: "2090136598679560679"
risk: medium
approval: yes
agents: [cto]
hooks: [cto.architecture-and-execution]
runtimes: [any]
summary: "Named local dev URLs and OAuth redirect setup. Pattern for G-Stack OAuth connectors; credential changes need approval."
---

# portless (OAuth local URLs)

Four-Signal 8/12. Fills the OAuth-redirect gap in connectors/g-stack/auth.py local testing.

## Provenance

- Source: X bookmark `2090136598679560679` (https://x.com/i/status/2090136598679560679)
- Upstream: https://github.com/vercel-labs/portless
- tenants/_demo/wiki/systems/ecosystem-candidates.md
- tenants/_demo/wiki/systems/skill-hook-crosswalk.md
- ~/.fieldtheory/library/taste/skills/vercel-labs-portless/ (2 SKILL.md: portless, oauth)

Pointer card. Nothing here is installed or wired into `workflows/skill-hooks.yaml`.

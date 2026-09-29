---
id: xmcp
name: "X MCP (xdevplatform)"
category: mcp
kind: mcp-server
disposition: add
repo: "https://github.com/xdevplatform/xmcp"
source: "2040937372909531286"
risk: high
approval: yes
agents: [dispatcher, librarian]
hooks: [dispatcher.virality-and-distribution]
runtimes: [any]
summary: "Official X platform MCP. Reads are fine; any post or DM waits for approval. Field Theory stays the bookmark store."
---

# X MCP (xdevplatform)

Four-Signal 7/12. Cursor already ships plugin-x-x; do not build a second X bus.

## Provenance

- Source: X bookmark `2040937372909531286` (https://x.com/i/status/2040937372909531286)
- Upstream: https://github.com/xdevplatform/xmcp
- tenants/_demo/wiki/systems/ecosystem-candidates.md
- tenants/_demo/wiki/systems/skill-hook-crosswalk.md

Pointer card. Nothing here is installed or wired into `workflows/skill-hooks.yaml`.

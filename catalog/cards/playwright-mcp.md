---
id: playwright-mcp
name: "Playwright MCP"
category: mcp
kind: mcp-server
disposition: add
repo: "https://github.com/microsoft/playwright-mcp"
source: "fleet-wings-2026-10-02"
risk: low
approval: no
agents: [cto]
hooks: []
runtimes: [any]
summary: "Browser automation over the accessibility tree: navigate, click, fill, snapshot. Local browser only; no credentials pass through it."
mcp:
  command: npx
  args: ["-y", "@playwright/mcp@latest"]
---

# Playwright MCP

Microsoft's MCP server that drives a real browser through structured accessibility snapshots instead of screenshots. The coding wing (`nodes/coding/node.yaml`) serves it for UI checks and smoke flows; the node's `mcps.playwright-mcp` repeats the launch spec.

It needs no token. Env values, when a tenant adds any, are variable names; secrets live in the runtime env or Keychain. Logging into a tenant's live accounts through it is a `connector-gate` decision, not a default.

---
id: figma-mcp
name: "Figma Context MCP"
category: mcp
kind: mcp-server
disposition: add
repo: "https://github.com/GLips/Figma-Context-MCP"
source: "fleet-wings-2026-10-02"
risk: medium
approval: no
agents: [interpreter]
hooks: []
runtimes: [any]
summary: "Read Figma files as structured layout data so the agent can implement a design from the source frame instead of a screenshot."
mcp:
  command: npx
  args: ["-y", "figma-developer-mcp", "--stdio"]
  env:
    FIGMA_API_KEY: "${FIGMA_API_KEY}"
---

# Figma Context MCP

Community MCP server (`figma-developer-mcp`) that fetches a Figma file or node and returns simplified layout, text, and style data. The design wing (`nodes/design/node.yaml`) serves it; the node's `mcps.figma-mcp` repeats the launch spec and wins at render.

Read-only against Figma. Env values are variable names; secrets live in the runtime env or Keychain. The tenant must still enable `figma-mcp` in `enabled.yaml`; the wing profile alone turns nothing on.

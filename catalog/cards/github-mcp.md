---
id: github-mcp
name: "GitHub MCP Server"
category: mcp
kind: mcp-server
disposition: add
repo: "https://github.com/github/github-mcp-server"
source: "fleet-wings-2026-10-02"
risk: medium
approval: no
agents: [cto]
hooks: []
runtimes: [any]
summary: "GitHub from the agent: issues, pull requests, code search, Actions. Writes still land as PRs and go through the repo's own review."
mcp:
  command: npx
  args: ["-y", "@modelcontextprotocol/server-github"]
  env:
    GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_PERSONAL_ACCESS_TOKEN}"
---

# GitHub MCP Server

MCP server for GitHub repositories, issues, pull requests, and Actions. The coding wing (`nodes/coding/node.yaml`) serves it; `nodes/coding/node.yaml` `mcps.github-mcp` carries the same launch spec and wins at render.

The `mcp:` block above launches the npm reference server; upstream also ships a Go binary and a Docker image (`github-mcp-server stdio`). Swap the launch spec in the node file if the Mac runs that instead.

Env values are variable names; secrets live in the runtime env or Keychain. Nothing here grants a token: the tenant must enable `github-mcp` in `enabled.yaml` and `connector-gate` still runs before every call.

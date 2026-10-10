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
  command: github-mcp-server
  args: ["stdio"]
  env:
    GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_PERSONAL_ACCESS_TOKEN}"
---

# GitHub MCP Server

MCP server for GitHub repositories, issues, pull requests, and Actions. The coding wing (`nodes/coding/node.yaml`) serves it; `nodes/coding/node.yaml` `mcps.github-mcp` carries the same launch spec and wins at render.

The `mcp:` block launches GitHub's official native server with `github-mcp-server stdio`. The former npm reference package is deprecated and is retained only in historical device-probe evidence. Install a reviewed upstream release with its version and checksum recorded before this launcher is used on a wing. A render does not install or authenticate the binary.

The default server capability set is preserved; each action remains subject to connector-gate and repository review. For a read-only probe, upstream supports `--read-only`. Company PAT or OAuth authentication is a separate device gate; the public anonymous legacy probe does not satisfy it. See https://github.com/github/github-mcp-server for supported installation and authentication.

Env values are variable names; secrets live in the runtime env or Keychain. Nothing here grants a token: the tenant must enable `github-mcp` in `enabled.yaml` and `connector-gate` still runs before every call.

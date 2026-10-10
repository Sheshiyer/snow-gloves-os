---
id: sg-connector-gate
name: "Snow Gloves connector gate"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-connector-gate"
risk: medium
approval: no
agents: [sentinel]
hooks: [sentinel.connector-gate]
runtimes: [claude]
summary: "skills/connector-gate as code: refuses hold and refuse cards, servers the tenant has not enabled, and high-risk or approval tools without an approved ticket."
---

# Snow Gloves connector gate

A first-party Claude Code mod at `mods/sg-connector-gate`. It hooks `tool.call` for `mcp__*` tools and decides from `scripts/sg_mods.py gate-table`, which joins `catalog/modules.json`, the tenant's `enabled.yaml`, and the approvals history.

It governs only the servers the catalog manages (categories `mcp` and `connector`, keyed by card id as the adapter writes `.mcp.json`). Every other MCP server, such as the claude.ai ERP connector, goes on untouched with `next(e)`, so the settings `PreToolUse` hooks that guard it (`erp-read-only.py`) still run. It never answers a call with a result and has no `tool.check` hook.

A high-risk or `approval: yes` tool without a grant queues a ticket through `sg_mods.py request-approval` and is refused until a person approves it in `/approvals`. A failure in the gate refuses calls to managed servers only. With no tenant set it only observes.

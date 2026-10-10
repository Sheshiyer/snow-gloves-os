---
id: sg-guard
name: "Snow Gloves guard"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-guard"
risk: medium
approval: no
agents: [sentinel]
hooks: []
runtimes: [claude]
summary: "ERP read-only guard, MCP result redaction, and a supply-chain check for other mods."
---

# Snow Gloves guard

A first-party Claude Code mod at `mods/sg-guard`: defense in depth beside `~/.claude/hooks/erp-read-only.py`. The ERP connector may only run `execute_read_only_query`, one bounded ids-only SELECT (a TypeScript port of `validate_query` plus the never-touch tables and personal columns); the guard refuses with `{ deny }` or passes on with `next(e)`, so the settings hook still runs after it. MCP results lose emails, phone numbers, card numbers and secrets (a port of `scripts/lib/redact.py`, tested against the same fixtures from Python). A `plugin.register` hook refuses user-tier mods that spawn, write files or fetch without an `add` card; it only takes effect when `sg-guard` is in `prependPlugins`. Every hook fails closed for its own scope.

---
id: sg-approvals
name: "Snow Gloves approvals desk"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-approvals"
risk: medium
approval: no
agents: [sentinel, chief-of-staff]
hooks: []
runtimes: [claude]
summary: "/approvals opens a pane of pending approval tickets across tenants, with approve and reject buttons only a person can press."
---

# Snow Gloves approvals desk

A first-party Claude Code mod at `mods/sg-approvals`: the "review desk" of `docs/SESSION-WORLD-DESIGN.md`. It lists pending tickets from `scripts/sg_mods.py snapshot` (payload keys only, never values) and decides them through `scripts/approvals.py approve|reject --actor`, which moves the ticket to `history.jsonl`.

Decisions are human-only: the mod registers no tool for Claude and submits no prompt, so only a button press decides. A high-risk approval asks for confirmation first. A 30-second timer toasts when new tickets arrive and never opens the pane by itself.

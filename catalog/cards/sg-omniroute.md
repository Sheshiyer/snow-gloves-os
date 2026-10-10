---
id: sg-omniroute
name: "Snow Gloves OmniRoute ledger"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-omniroute"
risk: low
approval: no
agents: [cto, sentinel]
hooks: []
runtimes: [claude]
summary: "Per-request token, cache and model ledger, a meter above the prompt, /omniroute and /combo."
---

# Snow Gloves OmniRoute ledger

A first-party Claude Code mod at `mods/sg-omniroute`. A `turn.step` hook records input, output and cache tokens and the model for every request, main conversation and subagents apart, and passes the result through unchanged. A line above the prompt shows context %, rate limits, cache share and cost from `$.session.usage()`. `/combo` lists the gateway's combos from OmniRoute's database opened read-only; the mod never reads its key and never changes the session's model.

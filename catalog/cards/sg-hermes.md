---
id: sg-hermes
name: "Snow Gloves Hermes console"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-hermes"
risk: low
approval: no
agents: [dispatcher, chief-of-staff]
hooks: []
runtimes: [claude]
summary: "/hermes: live event stream, route lens for a task title, replay through today's skill hooks."
---

# Snow Gloves Hermes console

A first-party Claude Code mod at `mods/sg-hermes`. Polls `GET /events?since=` on Hermes, posts a typed task title to `/test/e2e` to show which agent and hook route it, and runs `scripts/replay.py --last 20` to list events whose route would change. With the `publishTurns` option on, a finished turn posts a `claude.turn` event to `/publish` so `sentinel_sweep.py` has traffic to measure; a failed publish is dropped. `$.http.fetch` goes only to the Hermes endpoint.

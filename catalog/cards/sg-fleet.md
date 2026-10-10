---
id: sg-fleet
name: "Snow Gloves fleet cockpit"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-fleet"
risk: low
approval: no
agents: [cto, sentinel]
hooks: []
runtimes: [claude]
summary: "/fleet: this wing's doctor checks and which CLI surfaces point at the fleet gateway."
---

# Snow Gloves fleet cockpit

A first-party Claude Code mod at `mods/sg-fleet`. Every two minutes it runs `scripts/fleet/doctor.py --json` and `scripts/fleet/gateway_client.py status` (both read-only) and toasts when a critical check turns red. `/fleet` opens a pane of checks and surfaces, or answers in text where nothing draws a pane. A heat map and the coordinator task board are future work.

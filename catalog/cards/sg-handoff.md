---
id: sg-handoff
name: "Snow Gloves transfer dock"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-handoff"
risk: medium
approval: no
agents: [chief-of-staff]
hooks: []
runtimes: [claude]
summary: "/handoff writes .project/HANDOFF.md and tells another session; /inbox holds [sg] peer messages."
---

# Snow Gloves transfer dock

A first-party Claude Code mod at `mods/sg-handoff`. `/handoff [sessionId]` asks the session's own model for a handoff over its cached transcript, asks you to confirm, writes `.project/HANDOFF.md` through `sg_mods.py write-handoff` and sends the other session a pointer. `/inbox on` holds peer messages tagged `[sg]` instead of interrupting a turn. Hand to Claude submits one as a turn from a button a person pressed: the one documented exception to rule I3 (`$.prompt.submit`).

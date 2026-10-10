---
id: sg-catalog
name: "Snow Gloves catalog browser"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-catalog"
risk: medium
approval: yes
agents: [chief-of-staff, librarian]
hooks: []
runtimes: [claude]
summary: "/sg-catalog browses the catalog and enables a card; /sg-mod-review drafts a hold card for a third-party mod."
---

# Snow Gloves catalog browser

A first-party Claude Code mod at `mods/sg-catalog`. The pane filters `catalog/modules.json` by category and disposition and marks what the tenant has enabled. Enable runs `scripts/onboard.py --tenant T --enable ID` after a confirmation; hold, refuse and pointer cards show why and have no button. `/sg-mod-review <path>` runs `claude plugin validate --json` on a third-party mod and has `sg_mods.py draft-card` write a `hold` card flagging what rules I1 to I6 would refuse. Nothing is installed.

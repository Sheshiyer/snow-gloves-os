---
id: sg-rail
name: "Snow Gloves rail (status band)"
category: mod
kind: claude-mod
disposition: add
repo: ""
source: "snow-gloves-os/mods/sg-rail"
risk: low
approval: no
agents: [chief-of-staff]
hooks: []
runtimes: [claude]
summary: "Band above the Claude Code prompt: tenant, data root, Hermes and OmniRoute health, pending approvals, graph walk, ISA progress, and the Temperance rail. Adds /sg."
---

# Snow Gloves rail

A first-party Claude Code mod that ships in this repo at `mods/sg-rail` and loads in place from the `snowgloves-mods` directory marketplace.

It reads `scripts/sg_mods.py snapshot` every 30 seconds and probes the Hermes and OmniRoute `/healthz` endpoints. While it is loaded it sets `TEMPERANCE_RAIL_SINK=file`, so the Temperance PromptProcessing hook writes the rail to `~/.claude/MEMORY/STATE/rail/<session>.ui.json` and the band draws it, instead of the rail riding along in Claude's context on every prompt. It writes no files.

`claude plugin validate` calls: `$.process.run`, `$.http.fetch`, `$.fs.read`, `$.fs.exists`, `$.env.get`, `$.env.set` (TEMPERANCE_RAIL_SINK), `$.command.*`, `$.state.*`, `$.ui.*`, `$.clock.*`, `$.session.cwd`, `$.session.id`. See `docs/mods.md`.

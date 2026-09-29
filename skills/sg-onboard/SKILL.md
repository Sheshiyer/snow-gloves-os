---
name: sg-onboard
description: "Onboard a business into Snow Gloves OS with a plan-mode interview. Picks agents, skills, connectors, and runtimes from catalog/modules.json one decision at a time, writes snowgloves-harvest.md with FILL: for missing facts, then applies it to tenants/<slug>/. USE WHEN onboarding a tenant, choosing Snow Gloves modules, or setting up a runtime for Snow Gloves."
---

# sg-onboard — plan-mode onboarding

Runtime-agnostic. The founder picks the runtime; the runtime's adapter (`adapters/<runtime>/adapter.yaml`) says which question tool to use and where files go.

## Procedure

`python3 scripts/onboard.py --steps` prints the same list.

1. Interview. Print the prompt for this runtime and follow it exactly:

   `python3 scripts/onboard.py --prompt <runtime>`

   The prompt puts you in plan mode, asks one decision at a time with the runtime's question tool, and takes options from `catalog/modules.json`. It writes `snowgloves-harvest.md` and nothing else. Missing facts are `FILL:`; ask for them, never invent them.

2. Apply. Writes the tenant's context files, `enabled.yaml`, and `runtime.yaml`:

   `python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant <slug>`

3. Adjust. Browse and enable more later. Only `add` and `pointer` items can be enabled; `hold` and `refuse` are refused.

   `python3 scripts/onboard.py --list --category skills`
   `python3 scripts/onboard.py --enable id,id --tenant <slug>`

4. Render. Dry run first; `--write` only after the founder reads the plan.

   `python3 scripts/onboard.py --render-adapter <runtime> --tenant <slug>`
   `python3 scripts/onboard.py --render-adapter <runtime> --tenant <slug> --write`

## Rules

- Never hand-edit `enabled.yaml` to add a hold or refused id.
- Load `connector-gate` before any external tool call; it reads `tenants/<slug>/enabled.yaml`.
- A render never overwrites runtime config it does not own: JSON is merged, TOML tables are appended, YAML config gets a sibling `.snowgloves` fragment, and markdown rules get a marked block.

## Verification

`tenants/<slug>/enabled.yaml` lists exactly the chosen ids, `runtime.yaml` names the runtimes, and `tenants/<slug>/runtime/<runtime>/render.json` lists every file the last render wrote.

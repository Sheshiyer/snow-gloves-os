# Snow Gloves mods

Claude Code mods for Snow Gloves OS, published as the `snowgloves-mods` directory marketplace. Design, rules, and the ten mods: [`docs/mods.md`](../docs/mods.md).

| Mod | What it adds |
|---|---|
| [`sg-rail`](./sg-rail) | Band above the prompt (tenant, data root, Hermes, OmniRoute, approvals, graph walk, ISA, Temperance rail) and `/sg` |
| [`sg-connector-gate`](./sg-connector-gate) | `skills/connector-gate` enforced on catalog-managed MCP servers, and `/sg-gate` |
| [`sg-approvals`](./sg-approvals) | `/approvals`: the review desk pane, decided only by a person |
| [`sg-guard`](./sg-guard) | ERP read-only guard, MCP result redaction, supply-chain check for other mods, and `/sg-guard` |
| [`sg-hermes`](./sg-hermes) | `/hermes`: live events, route lens, replay; optional turn heartbeat to Hermes |
| [`sg-org`](./sg-org) | The seven agents as `sg-org:<slug>` subagent types, and `/org` |
| [`sg-omniroute`](./sg-omniroute) | Per-request token, cache and model ledger, a meter above the prompt, `/omniroute` and `/combo` |
| [`sg-fleet`](./sg-fleet) | `/fleet`: doctor checks and gateway state, with a toast when a critical check turns red |
| [`sg-handoff`](./sg-handoff) | `/handoff` writes `.project/HANDOFF.md` and tells another session; `/inbox` holds `[sg]` peer messages |
| [`sg-catalog`](./sg-catalog) | `/sg-catalog` browses and enables catalog cards; `/sg-mod-review` drafts a hold card for a third-party mod |

Needs Claude Code 2.1.287 or later. Tested with 2.1.287 (CLI) and 2.1.295 (Desktop).

Load them for one session from this checkout (hot-reloads on save):

```bash
make mods-dev T=_demo
```

Check them (validate, test, and the mod rules):

```bash
make mods-check
```

Each mod reads the platform through `scripts/sg_mods.py` and changes nothing on disk except through `scripts/approvals.py` and `sg_mods.py request-approval`. Options (`tenant`, `dataRoot`, `platformRoot`, and per mod `gateMode`, `ttlHours`, `actor`, `erpServerId`, `redactResults`, `supplyChain`, `hermesUrl`, `publishTurns`, `roleCombos`, `combosDb`) fall back to `SNOWGLOVES_TENANT`, `SNOWGLOVES_DATA`, and `SNOWGLOVES_ACTOR`.

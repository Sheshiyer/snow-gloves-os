# Snow Gloves mods

Claude Code mods for Snow Gloves OS, published as the `snowgloves-mods` directory marketplace. Design, rules, and the roadmap of ten mods: [`docs/mods.md`](../docs/mods.md).

| Mod | What it adds |
|---|---|
| [`sg-rail`](./sg-rail) | Band above the prompt (tenant, data root, Hermes, OmniRoute, approvals, graph walk, ISA, Temperance rail) and `/sg` |
| [`sg-connector-gate`](./sg-connector-gate) | `skills/connector-gate` enforced on catalog-managed MCP servers, and `/sg-gate` |
| [`sg-approvals`](./sg-approvals) | `/approvals`: the review desk pane, decided only by a person |

Needs Claude Code 2.1.287 or later. Tested with 2.1.287 (CLI) and 2.1.295 (Desktop).

Load them for one session from this checkout (hot-reloads on save):

```bash
make mods-dev T=_demo
```

Check them (validate, test, and the mod rules):

```bash
make mods-check
```

Each mod reads the platform through `scripts/sg_mods.py` and changes nothing on disk except through `scripts/approvals.py` and `sg_mods.py request-approval`. Options (`tenant`, `dataRoot`, `platformRoot`, and per mod `gateMode`, `ttlHours`, `actor`) fall back to `SNOWGLOVES_TENANT`, `SNOWGLOVES_DATA`, and `SNOWGLOVES_ACTOR`.

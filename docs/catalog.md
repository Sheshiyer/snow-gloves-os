# Catalog

The catalog is the list of third-party skills, MCP servers, plugins, connectors, and playbooks a tenant can choose from. It lives in `catalog/`:

| Path | What it is | Edit? |
|---|---|---|
| `catalog/SCHEMA.md` | The card schema (authoritative) | yes |
| `catalog/cards/<id>.md` | One card per module | yes |
| `catalog/registry.yaml` | Card index | no, generated |
| `catalog/modules.json` | Everything the dashboard and onboarding read (schema `snowgloves.modules.v1`) | no, generated |

A card is a **pointer**: front matter plus a short body explaining why the card exists and where it came from. It never contains a copy of upstream code.

## Current contents (v0.2.1)

132 cards.

| Disposition | Count | | Category | Count |
|---|---:|---|---|---:|
| `add` | 61 | | `skills` | 79 |
| `pointer` | 45 | | `playbook` | 36 |
| `hold` | 14 | | `plugin` | 13 |
| `refuse` | 12 | | `mcp` | 3 |
| | | | `connector` | 1 |

Sources: the X bookmark harvest, Field Theory taste packs (design, 2026-09-25, tutor), the Instagram saved harvest, founders-kit (one `fk-` pointer card per category), and [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (50 `ms-` cards). The reasoning behind each disposition, and the founder pick list, are in [research/2026-09-29-ecosystem-review.md](./research/2026-09-29-ecosystem-review.md).

`modules.json` also carries the 7 agents (with their routed skill counts from `skills/registry.yaml`), the 9 runtime adapters, the G-Stack connectors, and the platform `version`.

## Card schema

Front matter keys (see [`catalog/SCHEMA.md`](../catalog/SCHEMA.md) for the full table):

| Key | Values |
|---|---|
| `id` | kebab-case, equals the file name. `fk-` = founders-kit, `ms-` = marketingskills |
| `name` | display name |
| `category` | `skills` \| `mcp` \| `connector` \| `plugin` \| `playbook` |
| `kind` | free text: `skill`, `skill-pack`, `mcp-server`, `library`, `resource-list`, `runtime`, … |
| `disposition` | `add` \| `pointer` \| `hold` \| `refuse` |
| `repo` | upstream URL, or `""` if unresolved |
| `source` | X bookmark id, IG shortcode, or URL (quoted string) |
| `risk` | `low` \| `medium` \| `high` |
| `approval` | `yes` \| `no` |
| `agents` | agent slugs from `agents/*/MANIFEST.yaml` |
| `hooks` | optional `<agent>.<hook-id>` from `workflows/skill-hooks.yaml`; target area only, nothing is auto-wired |
| `runtimes` | subset of `any, hermes, claude, codex, cursor, opencode, grok, openclaw, muse` |
| `summary` | one line |

`build_catalog.py` exits 2 on an unknown category, disposition, risk, agent, hook, or runtime.

## Dispositions

| Disposition | Enableable | Rendered into a runtime | Meaning |
|---|---|---|---|
| `add` | yes | yes | Install it for the tenant |
| `pointer` | yes | no, listed as reference | The host already provides it, or it is read-only reference material. Don't install a second copy |
| `hold` | no | no | On the dashboard, waiting on a founder pick and a review |
| `refuse` | no | no | Reviewed and rejected; will never be enabled |

`scripts/onboard.py --enable` and `--apply-harvest` refuse `hold` and `refuse` ids with a reason. Re-running `--enable` re-checks previously enabled ids, so a card that moved to `hold` drops out loudly.

## Adding or changing a card

1. Create or edit `catalog/cards/<id>.md` following the schema.
2. Rebuild: `make catalog` (`python3 scripts/build_catalog.py`).
3. Confirm it is clean: `make catalog-check`. CI runs the same check.
4. Commit the card together with the regenerated `registry.yaml` and `modules.json`.

To promote a `hold` card, change its disposition to `add` or `pointer` after the review and rebuild. Tenants pick it up with `--enable`.

## Commands

```bash
make catalog                                        # rebuild registry.yaml + modules.json
make catalog-check                                  # exit 1 if stale
python3 scripts/onboard.py --list                   # every card
python3 scripts/onboard.py --list --category mcp --json
python3 scripts/onboard.py --enable id,id --tenant <slug>
```

`make release V=x.y.z` rebuilds the catalog automatically so `modules.json` carries the new version.

# Catalog card schema

Each file `catalog/cards/<id>.md` is a **pointer** to a third-party skill, MCP server, connector, plugin, or playbook. A card never contains a copy of the upstream code. `scripts/build_catalog.py` reads the cards and writes two files: `catalog/registry.yaml` (the card index) and `catalog/modules.json` (schema `snowgloves.modules.v1`, which also carries agents, adapters, and connectors). Both are generated, so don't edit them by hand. CI runs `--check`.

## Front matter

| Key | Values |
|---|---|
| `id` | kebab-case, must equal the file name. Prefixes: `fk-` for founders-kit categories, `ms-` for marketingskills skills |
| `name` | display name |
| `category` | `skills` \| `mcp` \| `connector` \| `plugin` \| `playbook` (code libraries and tools use `plugin`; reference lists and prompt kits use `playbook`) |
| `kind` | free text: `skill`, `skill-pack`, `mcp-server`, `library`, `resource-list`, `runtime`, … |
| `disposition` | `add` \| `hold` \| `refuse` \| `pointer` |
| `repo` | upstream URL, or `""` if unresolved |
| `source` | X bookmark id, IG shortcode, or URL (always a quoted string) |
| `risk` | `low` \| `medium` \| `high` |
| `approval` | `yes` \| `no` |
| `agents` | agent slugs from `agents/*/MANIFEST.yaml` |
| `hooks` | optional; `<agent>.<hook-id>` from `workflows/skill-hooks.yaml`. This is the target area only; nothing gets wired automatically |
| `runtimes` | subset of `any, hermes, claude, codex, cursor, opencode, grok, openclaw, muse` |
| `summary` | one line |

The body holds a short explanation of why the card exists, plus its provenance (source files, Field Theory pack path, upstream commit).

## Dispositions

- `add` means the tenant can enable it through `scripts/onboard.py --enable`.
- `pointer` means the tenant can enable it, but the host already provides it or it is a read-only reference, so don't install a second copy.
- `hold` means it shows on the dashboard but can't be enabled until the founder picks it and it passes a review.
- `refuse` means it shows on the dashboard and can never be enabled. This matches Factor's shelf.

`build_catalog.py` exits 2 on an unknown category, disposition, risk, agent, hook, or runtime.

# Upgrading tenants

A platform release changes code, the catalog, and adapters. It does not touch tenant folders. `scripts/upgrade.py` brings each tenant under `tenants/` forward to the platform `VERSION`.

## Commands

```bash
make upgrade                    # dry run, every tenant
make upgrade T=acme             # dry run, one tenant
make upgrade T=acme WRITE=1     # apply to one tenant
make upgrade WRITE=1            # apply to every tenant
```

These call `python3 scripts/upgrade.py [--tenant <slug>] [--write]`. **Dry run is the default.**

## What it does

For each tenant:

1. Reads `tenants/<slug>/.snowgloves-version`. A missing file means `0.1`.
2. If the tenant is already at `VERSION`, prints `at X, nothing to do`.
3. Otherwise copies the tenant to a scratch folder and runs every migration in `migrations/v<a>_<b>_to_v<c>_<d>.py` between the two versions, in order. Gaps between migrations are no-ops.
4. Writes the target version into the scratch copy's `.snowgloves-version`.
5. Prints a unified diff of the tenant folder, with file renames shown as `rename a -> b`. `_embed_cache/` is never touched.

Then, once for the run:

6. `scripts/build_catalog.py`, so `catalog/modules.json` is current.
7. For every tenant, and every runtime in its `runtime.yaml` that is not `enabled: false`: `scripts/onboard.py --render-adapter <runtime> --tenant <slug> --write`, so the runtime files match the new catalog and adapters.

In a dry run, steps 6 and 7 are printed as `[dry-run] would run: …` and nothing is written. With `--write`, the diff is applied to the real tenant folder, then the catalog is rebuilt and the adapters are re-rendered with `--write`.

Running `--write` twice is safe: the second run reports `nothing to do`.

## Migrations

| Migration | From → To | What it changes |
|---|---|---|
| `migrations/v0_1_to_v0_2.py` | 0.1 → 0.2 | Renames the pre-Hermes event bus to Hermes in tenant `.yaml`, `.yml`, `.md`, `.json`, `.txt`, and `.toml` files (config keys such as `*_channel` → `hermes_channel`, the port env var → `HERMES_PORT`). Renames the old `*-events.jsonl` audit log to `hermes-events.jsonl`, appending if both exist. Event logs and vector indexes keep their historical content. |

To check that nothing in the repo still uses the old names: `make legacy-check` (skips `.bak-*` backup folders, `.git`, `node_modules`, and build output).

## Writing a migration

1. Add `migrations/v<from>_to_v<to>.py` with `FROM = "0.2"`, `TO = "0.3"`, and `def migrate(tenant_dir: Path) -> list[str]`. It edits the folder it is given in place (always a scratch copy) and returns one note per change.
2. Skip `_embed_cache/`, `.git/`, and `node_modules/`. Don't rewrite event history; move it.
3. Make it idempotent: running it on an already-migrated tenant changes nothing.
4. Add a test in `tests/test_upgrade.py` with a fixture tenant, covering the dry-run diff and `--write`.

## Before upgrading `_demo`

`tenants/_demo/ingest-plan.json` and `tenants/_demo/vector-index.jsonl` still contain absolute paths to the old `snow-gloves-os-modular` clone. The migration does not rewrite them (they are historical data). Re-run the ingest and embed for `_demo` to regenerate them against this checkout:

```bash
python3 scripts/ingest.py _demo          # rewrites ingest-plan.json from tenants/_demo/sources.yaml
SNOWGLOVES_EMBED_BACKEND=stub make embed T=_demo
```

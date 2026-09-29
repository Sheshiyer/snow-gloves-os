# Project State

## Project Reference

Repository: `snow-gloves-os`
Branch: `chore/consolidate-modular` (uncommitted consolidation work)
Platform version: `0.2.0` (unreleased; `CHANGELOG.md` heading still says "unreleased")

## Current Position

Phase: v0.2.0 consolidation
Status: Active: build work done, release not cut
Last activity: README and docs rewritten; upgrade/release integration fixes

Progress: [████████░░] 80%

### Done in this phase

- Modular clone merged; Hermes naming everywhere (`scripts/hermes.py`, `make hermes`, port 4100); `make legacy-check` and `tests/test_legacy_names.py` guard it (skipping `.bak-*`)
- Catalog: 130 cards (59 add, 45 pointer, 14 hold, 12 refuse) → `catalog/registry.yaml` + `catalog/modules.json`; `build_catalog.py --check` in CI
- Ecosystem review: `docs/research/2026-09-29-ecosystem-review.md`
- 9 runtime adapters (`adapters/*/adapter.yaml`), plan-mode interview (`prompts/onboard-interview.md`, `skills/sg-onboard/`, `scripts/onboard.py`), `skills/connector-gate/`
- Release + upgrade: `VERSION`, `scripts/release.py` (now rebuilds the catalog on bump; `--check` covers `modules.json`), `scripts/upgrade.py` (now renders adapters with `--write` when applying), `migrations/v0_1_to_v0_2.py`, `ci.yml`, `release.yml` platform job
- Docs: README, `docs/architecture-overview.md`, `catalog.md`, `adapters.md`, `onboarding.md`, `RELEASING.md`, `UPGRADING.md`
- Tests: 119 pytest tests passing

### In flight (parallel)

- Modules dashboard + guided onboarding in `apps/onboarding/`, static site via `make site` (`npm run build:site`) and `.github/workflows/pages.yml` → https://sheshiyer.github.io/snow-gloves-os/

## Next steps

1. **Founder picks.** Walk the pick list in the ecosystem review; promote chosen `hold` cards to `add`/`pointer` and rebuild the catalog.
2. **Verify adapters.** Confirm every `verify: true` field against the real runtime (Muse is a guess throughout; OpenClaw question tool and plan mode; Codex `/plan`). Remove each `verify` entry once confirmed.
3. **Publish the release.** Commit the consolidation, merge to main, `make release V=0.2.0`, `make release-push V=0.2.0`, review and publish the draft release.

## Open items

- Bundle id changed to `com.tryambakam.snowgloves.onboarding`; may break OTA for existing v0.1.x installs. Test an update from v0.1.1 before publishing.
- `tenants/_demo/ingest-plan.json` and `vector-index.jsonl` still contain absolute paths to `snow-gloves-os-modular`; re-run ingest/embed for `_demo`.
- `distribution.yaml` has no `hermes_requires`.

## Session Continuity

Resume: run `temperance-next-wave --cwd .` and continue from "Next steps".

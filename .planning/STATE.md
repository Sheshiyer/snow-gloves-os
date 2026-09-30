# Project State

## 2026-09-30 — Mac fleet roadmap published

- Source version: `VERSION` reads `0.2.1`; the older consolidation notes below are historical and have not been used to infer current PR/release state.
- Active planning packet: `specs/005-node-bootstrap/{spec,plan,tasks}.md`.
- Roadmap: `.planning/GITHUB_ROADMAP.md`; issue map: `.planning/NODE-BOOTSTRAP-GITHUB-MAP.json`.
- GitHub Project: https://github.com/users/Sheshiyer/projects/22
- Umbrella: https://github.com/Sheshiyer/snow-gloves-os/issues/16
- Scope: layered CLI bootstrap, doctor/debug, verified org RBAC, secrets, remote runtime, distributed sessions, Session World, Axtech leads/campaigns/media, and 50-session acceptance.
- Readiness: planning/backlog. No new CLI, service, RBAC, vault, visualization, or fleet runtime implemented or live-verified.
- Existing Will-organ acceptance issue #8 is retained.
- Next: review contracts and open identity/hardware/storage decisions; begin foundation tasks #17/#18 after spec/plan review.
- Pickup: `.planning/NODE-BOOTSTRAP-HANDOFF.json`. No credential, deployment, paid-call, or external-send authority is implied.

---

# Historical consolidation checkpoint

## Project Reference

Repository: `snow-gloves-os`
Branch: `chore/consolidate-modular` (PR #10)
Platform version: `0.2.0` (unreleased; do **not** tag until PR is merged)

## Current Position

Phase: v0.2.0 consolidation
Status: Ready to merge PR #10, then tag v0.2.0
Last activity: CI pip-cache fix; README/docs/workflows for stable v0.2.0

Progress: [█████████░] 90%

### Done in this phase

- Modular clone merged; Hermes naming everywhere (`scripts/hermes.py`, `make hermes`, port 4100); `make legacy-check` and `tests/test_legacy_names.py` guard it (skipping `.bak-*`)
- Catalog: 132 cards (61 add, 45 pointer, 14 hold, 12 refuse) → `catalog/registry.yaml` + `catalog/modules.json`; `build_catalog.py --check` in CI
- Optional packs (not core): `inference-sh-agent-skills`, `explee-skills`
- Core registry: 4 native skills (`sg-onboard`, `gtm-brief-synthesis`, `tn-seed`, `connector-gate`)
- Ecosystem review: `docs/research/2026-09-29-ecosystem-review.md`
- 9 runtime adapters (`adapters/*/adapter.yaml`), plan-mode interview (`prompts/onboard-interview.md`, `skills/sg-onboard/`, `scripts/onboard.py`), `skills/connector-gate/`
- Release + upgrade: `VERSION`, `scripts/release.py`, `scripts/upgrade.py`, `migrations/v0_1_to_v0_2.py`, `ci.yml`, `release.yml`
- Graph: `make walk` GREEN; `make graph-upgrade` dry-run (no auto hook writes)
- Docs: README, architecture, catalog, adapters, onboarding, releasing, upgrading, MAC-MINI-SETUP, wiki/NLM
- Tests: 130 pytest tests passing

### In flight

- PR #10: https://github.com/Sheshiyer/snow-gloves-os/pull/10 — merge, then tag v0.2.0
- Pages workflow after merge
- Modules dashboard already in `apps/onboarding/`

## Next steps (after this PR lands)

1. **Merge PR #10.** Then `make release V=0.2.0` / `make release-push` — not before.
2. **Founder picks.** Walk the pick list in the ecosystem review; enable `add` cards per tenant. Do not auto-wire `hold` / `refuse`. Enable `inference-sh-agent-skills` or `explee-skills` only if those desks should fill.
3. **Verify adapters.** Confirm every `verify: true` field against the real runtime. Remove each `verify` entry once confirmed.
4. **Mac Mini first hour.** Follow `docs/MAC-MINI-SETUP.md` (doctor → smoke → walk → harvest). Do not install inference-sh/Explee in that hour.

## Open items

- Bundle id is `com.tryambakam.snowgloves.onboarding`; v0.2.0 is a new app — 0.1.x users reinstall (no OTA).
- `distribution.yaml` has no `hermes_requires` (intentionally unset for this release).

## Session Continuity

Resume after merge: tag v0.2.0, then founder picks — not more core routing.

# snow-gloves-os

Snow Gloves OS is a reusable, tenant-scoped business operations platform: seven agents (CEO, CTO, Chief of Staff, Librarian, Interpreter, Dispatcher, Sentinel), the Hermes event bus, G-Stack connectors, NVIDIA embeddings, and a Paperclip bridge. It is agent-agnostic: a catalog of third-party modules plus per-runtime adapters let the founder run it in Claude Code, Codex, Cursor, OpenCode, Grok, Hermes, OpenClaw, or any other agent.

## Current milestone: v0.2.0 consolidation

Goal: one repo, one version, one catalog, any runtime.

| Area | Deliverable | Status |
|---|---|---|
| Merge | Modular clone merged; Hermes naming everywhere | done |
| Catalog | `catalog/cards/` (132) → `modules.json`, `--check` in CI; inference-sh + Explee as packs | done |
| Research | `docs/research/2026-09-29-ecosystem-review.md` | done |
| Adapters + onboarding | 9 adapters, plan-mode interview, `scripts/onboard.py` | done; several adapter fields unverified |
| Dashboard | Tauri Modules dashboard + Pages site | in progress |
| Release + upgrade | `VERSION`, `release.py`, `upgrade.py`, migrations, CI | done; v0.2.0 not published |
| Docs | README + architecture, catalog, adapters, onboarding, releasing, upgrading | done |

## After v0.2.0

- Founder picks from the ecosystem review; promote `hold` cards
- Confirm unverified adapter fields
- Real NVIDIA NIM, Paperclip, and connector wiring for a pilot tenant

## Key files

- `README.md`, `AGENTS.md`, `CHANGELOG.md`, `VERSION`
- `docs/architecture-overview.md`, `docs/catalog.md`, `docs/adapters.md`, `docs/onboarding.md`, `docs/RELEASING.md`, `docs/UPGRADING.md`
- State: `.planning/STATE.md`

# Changelog

## v0.2.0 — Consolidated platform (unreleased)

- **Modular merge + Hermes naming.** The modular clone and the local tree are one repo; the event bus is Hermes everywhere (`scripts/hermes.py`, `HERMES_PORT`, `_audit/hermes-events.jsonl`, `hermes_channel`).
- **Catalog cards.** `catalog/` holds one card per harvested X/IG skill, founders-kit playbook, and marketingskills spoke, compiled to `catalog/modules.json` by `scripts/build_catalog.py`.
- **Runtime adapters + plan-mode onboarding.** `adapters/<runtime>/adapter.yaml` (hermes, claude, codex, cursor, opencode, grok, openclaw, muse, generic) and a portable plan-mode interview (`make onboard-prompt R=<runtime>`) that writes `snowgloves-harvest.md`, applied with `scripts/onboard.py`.
- **Modules dashboard + Pages site.** The Tauri app and a static Pages site render the same `modules.json` (agents, catalog, connectors, per-tenant enabled state).
- **Platform release + upgrade.** Root `VERSION` (platform `0.2.0`, app synced), `scripts/release.py` / `make release V=`, a `platform` release job shipping the source tarball, `modules.json`, and adapter bundles, and `scripts/upgrade.py` / `make upgrade [T=]` with `migrations/` (first: the old bus name to Hermes rename for tenant files).

## v0.1.1 — OTA verification

- Verifies the published v0.1.0 app can discover and install updates through the Tauri updater.
- No product behavior changes beyond version bump.

## v0.1.0 — First signed OTA release

- Signed and notarized macOS universal DMG.
- Windows and Linux installers.
- Public GitHub Releases updater manifest (`latest.json`).


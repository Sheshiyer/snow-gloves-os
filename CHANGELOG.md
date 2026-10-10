# Changelog

## Unreleased

- **Controller data audit.** Read-only tenant-reference verification and checksum-bound private-file holds, with a candidate transfer preflight that rejects declared paths and copied held bytes. Capability presence grants no runtime authority.

- **Manual Sentinel write review (source-only, default-off).** Owners can submit a read-only Sentinel verification child bound to a succeeded CTO write child's exact attempt and artifact checksum. The coordinator revalidates the binding and current authorization at claim, delivers bounded verified patch evidence, and the worker checks patch applicability without applying it. No automatic fanout, write, merge, or deployment authority is added.
- **Cloud gateway.** OmniRoute can run on EC2 behind Cloudflare instead of the Coding Mac: `infra/aws-gateway` (Elastic IP, Cloudflare-only security group, SSM, S3 backups, DLM snapshots, alarms, budget) and `infra/cloudflare-gateway` (proxied DNS, Origin CA cert via SSM, WAF office allowlist on `/v1`, Access on the dashboard), driven by `scripts/fleet/cloud_gateway.sh`. `scripts/fleet/cloud_guard.py` and the doctor's `fleet-boundary` check refuse any account, zone or domain outside the `cloud_gateway` block. `gateway_client.py` takes `--url https://…` and `--via tailnet`. Docs: `docs/fleet/08-CLOUD-GATEWAY.md`.

## v0.2.1 — Onboarding TUI (2026-09-30)

- **TUI + headless runner.** `make tui` / `scripts/tui_onboard.py` walks doctor, smoke, walk, harvest apply, catalog enable, render, and graph-upgrade dry-run. Toggle agent vs manual TUI; agent needs `claude`, `codex`, or `kimi`/`kimi-cli` on PATH or it falls back. Agents: `--headless`. `hold`/`refuse` stay refused. Hermes is not started headless.
- **macOS release.** CI skips Apple notarization when `APPLE_CERTIFICATE` is unset so the DMG can attach.

## v0.2.0 — Consolidated platform (2026-09-29)

- **Modular merge + Hermes naming.** The modular clone and the local tree are one repo; the event bus is Hermes everywhere (`scripts/hermes.py`, `HERMES_PORT`, `_audit/hermes-events.jsonl`, `hermes_channel`).
- **Catalog cards.** `catalog/` holds one card per harvested X/IG skill, founders-kit playbook, and marketingskills spoke, compiled to `catalog/modules.json` by `scripts/build_catalog.py` (132 cards). inference-sh and Explee are optional `add` packs, not core hooks.
- **Runtime adapters + plan-mode onboarding.** `adapters/<runtime>/adapter.yaml` (hermes, claude, codex, cursor, opencode, grok, openclaw, muse, generic) and a portable plan-mode interview (`make onboard-prompt R=<runtime>`) that writes `snowgloves-harvest.md`, applied with `scripts/onboard.py`.
- **Modules dashboard + Pages site.** The Tauri app and a static Pages site render the same `modules.json` (agents, catalog, connectors, per-tenant enabled state).
- **Graph walk.** `make walk` machine-checks CoS routing and native inner loops; `make graph-upgrade` is a dry-run learning edge (hook writes need approval).
- **Platform release + upgrade.** Root `VERSION` (platform `0.2.0`, app synced), `scripts/release.py` / `make release V=`, a `platform` release job shipping the source tarball, `modules.json`, and adapter bundles, and `scripts/upgrade.py` / `make upgrade [T=]` with `migrations/` (first: the old bus name to Hermes rename for tenant files). **0.1.x must reinstall** (`com.tryambakam.snowgloves.onboarding`).

## v0.1.1 — OTA verification

- Verifies the published v0.1.0 app can discover and install updates through the Tauri updater.
- No product behavior changes beyond version bump.

## v0.1.0 — First signed OTA release

- Signed and notarized macOS universal DMG.
- Windows and Linux installers.
- Public GitHub Releases updater manifest (`latest.json`).


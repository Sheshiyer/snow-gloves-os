## 2026-10-05 — Branches reconciled locally; Axtech brand map confirmed by the founder

- Local `main` is the single head (fast-forwarded to the fleet work at 58e77d8); nine merged local branches deleted (restore SHAs kept in the session scratchpad); `codex/local-mini-pilot` kept as an alias until push. The founder deleted six merged remote branches; PR #9 closed with them. Three remote branches remain for review: `ecc-tools/…` (PR #6, closed unmerged) and two `local-004-seed-briefs-dispatcher-*` backups.
- Not pushed: the GitHub repo is public and the unpushed range carries tailnet, LAN and account details; publishing waits on the founder's decision. The repo is shallow at 3353e52; an incremental push is fine, a full bundle is not.
- Brand map (`specs/006-editorial-steward-integration/founder-intake-2026-10-05.md`): ten branch tenants under Axtech plus AXIO under Metagration; projects `axtech-shop`, `safvr-channel`, `iverif` (under `cee-management`); `savewatt` and `iverif` tenant folders removed; three cross-brand flows proposed, none approved.
- Coding Mac: its checkout is 9 commits behind and clean; a second checkout `~/code/snow-gloves-os` there holds uncommitted work, including a 2026-09-30 `tenants/axio/` interview that describes AXIO differently (lead generation via getleads.io). Not merged; recorded as an open question.
- Verification: `python3 -m pytest -q` 279 passed; `scripts/build_catalog.py --check` up to date.

## 2026-10-02 14:10 UTC — Cutover complete, single live gateway

- The Coding Mac is the only OmniRoute; the seat's clients target `coding-mac` and its loopback 20128 forwards there under the original LaunchAgent label. Rollback path recorded in docs/fleet/DECISIONS.md.

## 2026-10-02 13:35 UTC — Gateway live on the tailnet

- `coding-mac` and `authoring-mini` are on tailnet `tail32e298.ts.net`; the gateway serves only on the Coding Mac's tailnet address; verified from the seat by name with a live completion.
- Next: founder's cutover decision, scoped keys, Marketing and Design minis.

## 2026-10-02 13:10 UTC — Coding Mac gateway live on the LAN

- First physical mini accepted for the gateway role: see `docs/fleet/ACCEPTANCE-2026-10-02-coding-mac.md`.
- OmniRoute 3.8.50 runs on AXIO's Mac mini bound to 192.168.0.35:20128; route test from the seat passed on both API styles.
- Remaining founder steps: `tailscale up`, power policy (sudo), cutover decision, scoped keys.

# 2026-10-02: Fleet wings implemented on the authoring seat

- The fleet is three Paris Mac minis by function: marketing, design, coding (`fleet.yaml`, schema `snowgloves.fleet.v1`). The Coding Mac hosts OmniRoute :20128 and Hermes :4100 for the whole fleet over Tailscale. The founder's current mini is the authoring seat, not a wing.
- Two axes: tenant = brand (`tenants/<slug>/enabled.yaml`, still the connector-gate authority) and node = wing (`nodes/<wing>/node.yaml`). A render for brand x wing x runtime is enableable(enabled intersect node.modules) plus node.mcps, written into that runtime's adapter paths.
- Landed this session: `fleet.yaml`; `nodes/<wing>/node.yaml` for the three wings; `scripts/lib/nodes.py`; `scripts/fleet/node_profile.py` (render, enable); `scripts/fleet/gateway_client.py`; `scripts/fleet/gateway_kit.sh` (export, verify); `scripts/fleet/remote_access.sh` (dry-run); `scripts/fleet/connect.sh`; `scripts/fleet/doctor.py`; `make fleet-doctor|fleet-render|fleet-enable|fleet-connect|fleet-kit-export|fleet-remote-access`; `scripts/approvals.py --actor` recorded as `decided_by`; `docs/fleet/`; `specs/007-fleet-wings/`.
- Start reading at `docs/fleet/README.md`, then `docs/fleet/DECISIONS.md` and `specs/007-fleet-wings/spec.md`. Roadmap: R14 in `.planning/GITHUB_ROADMAP.md` (relates to #20; issue to be opened). Pickup: `.planning/FLEET-WINGS-HANDOFF.json`.
- Founder decisions 2026-10-02: Tailscale overlay; the Coding Mac hosts the gateway and the authoring seat hands off a kit; one company Apple Account plus a shared `sg-<wing>` operator user per wing; subscription seats shared now with provider terms confirmed later (overrides Temperance ACP rule #4; recorded in `docs/fleet/DECISIONS.md`).
- Verification: `python3 -m pytest -q tests/` green (138 baseline plus the fleet doctor and approvals actor tests). `make fleet-doctor W=coding` on this seat passes its critical checks (node profile, local gateway, tenants); Tailscale not installed and Hermes down show as warnings, as expected here.
- Founder next: archive the modular clone; confirm the four brands' parent companies; install Tailscale on this seat and the three minis; amend ACP rule #4; rotate the OmniRoute dashboard password; fix the omniroute MCP key scope; `make fleet-kit-export` here, import on the Paris Coding Mac and do the provider OAuth sign-ins there; then `make fleet-doctor` on each wing for physical acceptance.
- The one-mini pilot below is unchanged (`.planning/HANDOFF.json`, status `pilot-route-decision-pending`); its `apply` consumes `nodes/<wing>/node.yaml` when it lands. Nothing was committed, pushed, installed on a Paris mini, or signed in.

---

# Current pickup — one-mini local pilot

- User confirmed 1 October 2026 scope: one Mac mini local bootstrap, doctor, resume/rollback pilot.
- Review: old CLI draft has 20 passing tests and 1 failure; old policy draft has 42 passing tests but a reproduced digest collision and optional approval verification. Neither integrated.
- Pinned free generation repeatedly failed bounded runs; no active workers remain.
- Implementation is pending an explicit native-model routing override requested in this chat.
- Pilot contract: `.planning/PILOT-CONTRACT.md`; ISA: `ISA.md` (0/20 implementation criteria).
- Prepared drafts: `.planning/pilot-drafts/LOCAL-MINI-PILOT.md` and controller tests beside it.
- Current implementation remains the existing baseline: 138 passing tests; catalog up to date.
- No installation kit, live activation, physical mini/reboot/restore proof, push, or deployment occurred.
- Resume from `.planning/HANDOFF.json`; do not treat draft commands as available.

---

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

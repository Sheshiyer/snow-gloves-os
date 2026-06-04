# Tasks: Orchestration Wiring — Explee → Dispatcher + Tryambakam Noesis Tenant

> **Status (2026-06-03):** Phases A–D complete; Phase E verified except live approval-gate
> enforcement and the runtime secret bind (both noted). Paperclip company **Tryambakam Noesis**
> created (`TRY`, `e97ff473-f919-404e-b59c-5591e9c3e9ae`); bridge resolves it; `make smoke` ✅.

## Phase A — Skill wiring (Explee → Dispatcher)

- [x] T001 `sources:` override map in `skills/registry.yaml` (`explee: Sheshiyer/explee-skills@`)
- [x] T002 Explee cluster under `dispatcher` (totals 10/67)
- [x] T003 `dispatcher.gtm-and-prospecting` hook → `[explee-orchestrator]`
- [x] T004 `dispatcher/SKILLS.md` Explee cluster section (entry = explee-orchestrator)
- [x] T005 `dispatcher/MANIFEST.yaml` approvals for `explee.paid_search/enrichment/autogtm`

## Phase B — G-Stack connector

- [x] T010 `explee_proxy` connector registered in `capabilities.yaml`
- [x] T011 paid caps flagged `risk: approval`; reads = `low`
- [ ] T012 runtime bind of `X-Proxy-Token` — `auth.py` already supports it (vault ref); the bind is an
      operational step pending the proxy token, not a code change. Connector is registered.

## Phase C — Tryambakam Noesis tenant

- [x] T020 `tenants/tryambakam-noesis/MANIFEST.yaml`
- [x] T021 `sources.yaml` → brand-docs-final + Content-Engine
- [x] T022 added to `tenants/_registry.yaml`

## Phase D — Paperclip company

- [x] T030 Paperclip reachable (`:3100` → http 200)
- [x] T031 company created — **Tryambakam Noesis** (`TRY`, `e97ff473-f919-404e-b59c-5591e9c3e9ae`)
- [x] T032 `company_id` + `lane_prefix` backfilled into the tenant MANIFEST
- [x] T033 outbox fallback verified (unused — Paperclip was live)

## Phase E — Verify

- [x] T040 route resolves: `dispatcher → explee-orchestrator` (bridge dry-run + hook tag)
- [ ] T041 live approval-gate enforcement test — gates are *declared* (MANIFEST `approvals_required`
      + connector `risk: approval`); live enforcement test pending the interpretation/policy engine
- [x] T042 bridge dry-run tags `snowgloves:tenant:tryambakam-noesis` + real `company_id`
- [x] T043 brand-safety guard documented (spec non-goal + dispatcher SKILLS: partner intel only)
- [x] T044 `make smoke` ✅ (end-to-end still green after wiring)
- [x] T045 external-source `sources:` pattern documented (registry + spec US3)

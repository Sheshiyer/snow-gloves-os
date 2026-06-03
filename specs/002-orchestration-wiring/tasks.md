# Tasks: Orchestration Wiring — Explee → Dispatcher + Tryambakam Noesis Tenant

## Phase A — Skill wiring (Explee → Dispatcher)

- [ ] T001 Add a `sources:` override map to `skills/registry.yaml` (`explee: Sheshiyer/explee-skills@`)
- [ ] T002 Register the Explee cluster under `dispatcher` in `skills/registry.yaml` (`explee-orchestrator` + search/enrichment/agents/autogtm/auth-cookie/api-core); update `totals`
- [ ] T003 Add `dispatcher.gtm-and-prospecting` hook to `workflows/skill-hooks.yaml` (globs `*icp* *prospect* *find compan* *find people* *enrich email* *gtm* *lead list* *partner finder*` → `[explee-orchestrator]`)
- [ ] T004 Update `agents/dispatcher/SKILLS.md` — list the Explee cluster + note `explee-orchestrator` as the single entry point
- [ ] T005 Add `approvals_required: [explee.paid_search, explee.enrichment]` to `agents/dispatcher/MANIFEST.yaml`

## Phase B — G-Stack connector

- [ ] T010 Register `explee-proxy` in `connectors/g-stack/capabilities.yaml` (base_url = deployed Worker origin; capabilities: search, agents, enrich, autogtm)
- [ ] T011 Flag paid capabilities `risk: approval` (`paid_search`, `enrichment`, `autogtm`); list/read meta = `read`
- [ ] T012 Reference `X-Proxy-Token` as a G-Stack tenant secret in `connectors/g-stack/auth.py` (secret store; not committed)

## Phase C — Tryambakam Noesis tenant

- [ ] T020 Create `tenants/tryambakam-noesis/MANIFEST.yaml` (business_name "Tryambakam Noesis", `isolation: strict`, `paperclip: {company_id: "", lane_prefix: ""}`, `status: active`)
- [ ] T021 Create `tenants/tryambakam-noesis/sources.yaml` → `brand-docs-final/` + `Content-Engine/`
- [ ] T022 Add `tryambakam-noesis` to `tenants/_registry.yaml`

## Phase D — Paperclip company

- [ ] T030 Ping Paperclip (`python scripts/paperclip_bridge.py --tenant tryambakam-noesis --ping`)
- [ ] T031 Create the "Tryambakam Noesis" company via the `paperclip` API/skill
- [ ] T032 Backfill `company_id` + `lane_prefix` (derived from business name) into the tenant MANIFEST
- [ ] T033 If Paperclip is down: confirm the bridge queues to `tenants/tryambakam-noesis/bridge_outbox.jsonl` (no task dropped)

## Phase E — Verify (constitution gates)

- [ ] T040 Route-test: a "find partner podcasts for the tryambakam ICP" task globs → `dispatcher → explee-orchestrator` (US1)
- [ ] T041 Approval-gate test: a paid Explee op halts at the gate, logs, escalates (Constitution #4)
- [ ] T042 Bridge dry-run: `--tenant tryambakam-noesis --dry-run` emits a payload tagged `snowgloves:tenant:tryambakam-noesis` (US2)
- [ ] T043 Brand-safety guard: confirm no cold-individual-outreach path is reachable from the Explee wiring
- [ ] T044 `make smoke` still green end-to-end
- [ ] T045 Document the `sources:` external-cluster pattern for reuse (US3)

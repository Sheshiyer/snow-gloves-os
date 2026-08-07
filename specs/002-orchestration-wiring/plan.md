# Implementation Plan: Orchestration Wiring — Explee → Dispatcher + Tryambakam Noesis Tenant

> Pure wiring/registration on existing layers — **no new engine**. Maps onto the four reusable
> engines (Connector · Knowledge · Interpretation · Orchestration).

## Components Touched

1. **Skill Registry & Routing** *(Interpretation layer)*
   - `skills/registry.yaml` — add Explee cluster under `dispatcher`; add a `sources:` override map so external clusters resolve outside the default `inference-sh/agent-skills@` prefix.
   - `workflows/skill-hooks.yaml` — add `dispatcher.gtm-and-prospecting` hook → `[explee-orchestrator]`.
   - `agents/dispatcher/SKILLS.md` + `MANIFEST.yaml` — list the cluster; add `approvals_required` for paid ops.

2. **Connector Fabric** *(G-Stack)*
   - `connectors/g-stack/capabilities.yaml` — register the `explee-proxy` connector + per-capability risk flags.
   - `connectors/g-stack/auth.py` — reference `X-Proxy-Token` from the secret store (never committed).

3. **Tenant Model** *(Orchestration / tenant isolation)*
   - `tenants/tryambakam-noesis/MANIFEST.yaml` + `sources.yaml`; add to `tenants/_registry.yaml`.

4. **Paperclip Bridge** *(Orchestration layer)*
   - **No code change** — `paperclip_bridge.py` already resolves `company_id` from the tenant MANIFEST and degrades to the local outbox. Create the company via the `paperclip` API/skill, then backfill `company_id` + `lane_prefix`.

## Data / Contract Additions

- `registry.sources` *(new)* — map `<prefix> → repo@`, e.g. `explee: Sheshiyer/explee-skills@`.
- `dispatcher.approvals_required += [explee.paid_search, explee.enrichment]`.
- `connector:explee-proxy` — `{ base_url, auth: {header: X-Proxy-Token, secret_ref}, capabilities[], risk_flags }`.
- `tenant:tryambakam-noesis` — `{ business_name, paperclip: {company_id, lane_prefix}, isolation: strict, sources[] }`.

## Delivery Phases

### Phase A — Skill wiring (Explee → Dispatcher) · US1
registry `sources` override + dispatcher skills + routing hook + manifest approvals + SKILLS.md.

### Phase B — Connector · US1
`explee-proxy` in `capabilities.yaml` + auth secret reference + read/approval risk flags.

### Phase C — Tenant scaffold · US2
`tryambakam-noesis` MANIFEST + sources + `_registry`.

### Phase D — Paperclip company · US2
create company via the `paperclip` skill; backfill `company_id` + `lane_prefix`; dry-run the bridge (or confirm outbox fallback if `:3100` down).

### Phase E — Verify · US1/US2/US3
route-test (glob → `dispatcher → explee-orchestrator`); approval-gate test (paid op halts); bridge dry-run tagged tenant; brand-safety guard (no cold-individual path reachable); `make smoke` green.

## Constitution Gates (must pass before "done")

- **#1 Spec before code** — this spec/plan/tasks approved first.
- **#2 Tenant isolation** — Explee runs tenant-scoped; `tryambakam-noesis` strict.
- **#3 Interpretation before automation** — Explee only via a routed decision (Phase E route-test).
- **#4 Approval-gated risk** — paid Explee ops gated (Phase E gate-test).
- **#5 Auditability** — bridge `snowgloves:tenant:` tags + SG Bus audit present.
- **#7 Portable packs** — the `sources:` external-cluster pattern is reusable.

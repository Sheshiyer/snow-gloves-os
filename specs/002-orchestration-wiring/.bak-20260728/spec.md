# Feature Spec: Orchestration Wiring — Explee → Dispatcher + Tryambakam Noesis Tenant

## Feature Branch

`002-orchestration-wiring`

**Created**: 2026-06-03 · **Status**: Draft

## Goal

De-silo three currently-standalone capabilities into Snow Gloves OS so they run as registered,
governed capabilities on the right agents under a first-class tenant — instead of separate repos
and one-off skills:

- the **Explee skill cluster** (`Sheshiyer/explee-skills`) + its deployed `explee-proxy` Worker,
- the **Tryambakam Noesis** org (brand-docs + Content-Engine), currently absent from Paperclip,
- (later) the **distribution OS** (`tn-seed` community-seeding) — out of scope here, see Non-Goals.

**This slice** wires the Explee cluster to the **Dispatcher** agent and stands up a
`tryambakam-noesis` tenant bridged to a Paperclip company. Everything routes through the existing
Hermes → Chief-of-Staff → Dispatcher → Paperclip path, with approval gates and audit.

## User Stories

### US1 — Explee callable via Dispatcher (Priority: P1)

As an operator, when a task/event matches GTM / prospecting / partner-outreach intent, the
Chief of Staff routes it to the **Dispatcher**, which invokes the Explee cluster (via
`explee-orchestrator`) through the approval-gated `explee-proxy` connector — so prospect/partner
intelligence runs *inside* the orchestration (interpreted, gated, audited), not as a side silo.

**Independent test**: post a Hermes event titled "find partner podcasts for tryambakam-noesis ICP";
assert it routes `dispatcher → explee-orchestrator`, and that a paid search requires approval.

### US2 — Tryambakam Noesis as a tenant/org (Priority: P2)

As an operator, I can run workflows scoped to a `tryambakam-noesis` tenant whose knowledge sources
are the brand-docs + Content-Engine, and whose actions land in a dedicated **Paperclip company
lane** — so the vocation org is first-class and tenant-isolated.

**Independent test**: `paperclip_bridge.py --tenant tryambakam-noesis --dry-run` resolves the tenant
and emits a payload tagged `snowgloves:tenant:tryambakam-noesis` with the resolved company lane (or
cleanly queues to the local outbox if Paperclip `:3100` is down).

### US3 — External skill-cluster registration pattern (Priority: P3)

As a platform maintainer, I can register a skill cluster that lives in a *different* repo via a
`sources:` override in `skills/registry.yaml` — so future external clusters de-silo the same way
without forking the single `source_prefix`. (Constitution #7, portable packs.)

### Edge Cases

- Paperclip `:3100` unreachable → bridge queues to `tenants/tryambakam-noesis/bridge_outbox.jsonl` (existing fallback); no task dropped.
- A GTM task with no approval for a paid op → Dispatcher halts at the approval gate, logs, escalates.
- Explee cookies stale → proxy falls back to `X-API-Key`; if both fail, surface, do not silently drop.

## Functional Requirements

1. `skills/registry.yaml` MUST list the Explee cluster (`explee-orchestrator` + spokes) under `dispatcher`.
2. `skills/registry.yaml` MUST support a per-cluster `sources:` override so `Sheshiyer/explee-skills@*` skills resolve independently of the default `inference-sh/agent-skills@` prefix.
3. `workflows/skill-hooks.yaml` MUST add a `dispatcher.gtm-and-prospecting` hook (globs: `*icp*`, `*prospect*`, `*find compan*`, `*find people*`, `*enrich email*`, `*gtm*`, `*lead list*`, `*partner finder*`) → `[explee-orchestrator]`.
4. `agents/dispatcher/MANIFEST.yaml` MUST add `approvals_required` for paid Explee ops (`explee.paid_search`, `explee.enrichment`); `agents/dispatcher/SKILLS.md` MUST list the cluster.
5. `connectors/g-stack/capabilities.yaml` MUST register an `explee-proxy` connector (the deployed Worker origin + `X-Proxy-Token` auth) with per-capability risk flags: `agents`/`search` = read; `paid_search`/`enrichment`/`autogtm` = `risk: approval`.
6. A `tryambakam-noesis` tenant MUST exist (`tenants/tryambakam-noesis/MANIFEST.yaml` + `sources.yaml`), added to `tenants/_registry.yaml`, `isolation: strict`.
7. The tenant MUST resolve to a Paperclip company (`paperclip.company_id` + `lane_prefix` derived from "Tryambakam Noesis"); until the company exists, the bridge MUST degrade to the local outbox.
8. `tenants/tryambakam-noesis/sources.yaml` MUST point at `brand-docs-final/` + `Content-Engine/` for ingest/embed.
9. Every Explee invocation MUST pass through a routed, logged decision (interpretation + Hermes audit) — no raw cold-scrape → action. (Constitution #3, #5.)

## Non-Goals (v1)

- Building the `tn-seed` distribution-OS skill (separate follow-up spec; it consumes Explee partner output + Content-Engine via Interpreter/Dispatcher).
- Splitting Explee across Librarian/Dispatcher (decided: single home = Dispatcher).
- **Cold outbound to scraped individuals** — brand-prohibited; Explee is partner/channel intelligence only.
- Real NVIDIA NIM embedding (stub backend acceptable here).
- Generalizing the external-source mechanism beyond the one `sources:` entry needed now.

## Success Metrics

- 100% of GTM/prospecting/partner tasks route `dispatcher → explee-orchestrator` on first pass.
- 100% of paid Explee ops (`paid_search`/`enrichment`/`autogtm`) pass an approval gate.
- `tryambakam-noesis` resolves a Paperclip `company_id` — or cleanly queues to outbox when Paperclip is down — with **0 dropped tasks**.
- **0** cold-individual-outreach actions emitted on the Explee path (brand-safety guard).
- Spec → plan → tasks approved before any registry/manifest edit (Constitution #1).

## Key Entities

- **Explee cluster** — `explee-orchestrator` (hub; routes internally) + search/enrichment/agents/autogtm + auth-cookie + api-core.
- **`explee-proxy` connector** — deployed token-gated Worker (cookie→KV→`api.explee.com`, `X-API-Key` fallback).
- **`tryambakam-noesis` tenant** — org; sources = brand-docs + Content-Engine; bound to a Paperclip company.
- **Dispatcher** — distribution/outreach agent; Explee's home; owns the Paperclip lane.

## Constitution Alignment

| # | Principle | How this spec honors it |
|---|---|---|
| 1 | Spec before code | This spec gates every wiring edit. |
| 2 | Tenant isolation first | Explee runs tenant-scoped; `tryambakam-noesis` isolation strict. |
| 3 | Interpretation before automation | Explee invoked only via routed decisions, never raw scrape→act. |
| 4 | Approval-gated risk | Paid Explee ops gated; connector flags `risk: approval`. |
| 5 | Auditability by default | Hermes audit + `snowgloves:tenant:` bridge tags on every task. |
| 6 | Wiki as human control surface | Tenant sources = brand-docs + Content-Engine (the operator wiki). |
| 7 | Portable domain packs | The `sources:` external-cluster pattern is reusable for any future cluster. |

## Assumptions

- The `explee-proxy` Worker is deployed and reachable (smoke-tested 200).
- Paperclip `:3100` may or may not be live; the bridge degrades gracefully either way.
- The cluster is invoked through `explee-orchestrator` as the single entry point.

## Resolved Decisions

- **Paperclip company creation** → via the **`paperclip` API/skill** (control plane), then backfill
  `company_id` + `lane_prefix` into the tenant `MANIFEST.yaml`. If `:3100` is unreachable at run time,
  scaffold the tenant and queue to the outbox; create the company when reachable.
- **Connector auth** → via the deployed **`explee-proxy`** Worker (cookie-first + `X-API-Key` fallback
  handled server-side); the `X-Proxy-Token` is stored as a **G-Stack tenant secret**
  (`connectors/g-stack/auth.py` secret store), never in committed config.

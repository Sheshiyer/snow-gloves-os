# Feature Spec: Brand-Enriched AutoGTM (brand-docs → Explee ICP)

## Feature Branch

`004-brand-enriched-autogtm`

**Created**: 2026-06-04 · **Status**: Draft

## Goal

Replace AutoGTM's thin website-scrape with the **deep brand corpus**. Synthesize **two structured ICP
Briefs** (Partner/Channel + B2B Customer) from `brand-docs-final`, human-approve them, and use them to
seed Explee AutoGTM — orchestrated through Paperclip, tenant-scoped to `tryambakam-noesis`.

**The Brief *is* the enriched "brand registration."** Core principle: the **agent synthesizes** (rare,
reasoning-heavy, human-approved) and the **API executes** (frequent, deterministic) — a layer boundary,
not either/or. This is constitution #3 (interpretation before automation) made concrete.

## User Stories

### US1 — Two ICP Briefs synthesized from the corpus (Priority: P1)

As the operator, a Paperclip task has the **Librarian** retrieve `brand-docs-final` and the
**Interpreter** synthesize two ICP Briefs — **Partner/Channel** (who amplifies us) and **B2B Customer**
(who would license/embed Selemene) — each a structured `{companies_filters, people_filters, exclusions,
outreach_angle, fit_criteria}`, written to the vault for my review. So Explee targets from my real brand
definition (persona, positioning, niche, competitor), not scraped marketing copy.

**Independent test**: run the synthesis task → `Content-Engine/_gtm/brief-partner.md` +
`brief-customer.md` exist, each with a populated multi-field filter object traceable to the brand-docs.

### US2 — An approved Brief drives AutoGTM (Priority: P1)

As the Dispatcher, `brand_to_gtm(brief)` turns an **approved** Brief into the Explee payload and runs
`nl-to-filters` → `companies`/`people` → `enrich` through the `explee-proxy` connector (paid ops
approval-gated, per 002), returning candidates. So a knowledge-grounded ICP — not a URL — seeds the run.

**Independent test**: `brand_to_gtm(brief_fixture, fetch=fake)` builds the expected Explee payload and
returns normalized candidates (no live network in the test).

### US3 — Brand-fit re-scoring (Priority: P2)

As the Interpreter, AutoGTM results are re-ranked against the brand's **positioning/differentiators
(Kha-Ba-La fit)**, with fit reasons — so the list reflects *our* fit, not generic firmographics.

### US4 — Refresh routine (Priority: P3)

As the ecosystem, a Paperclip **routine** `refresh-gtm-briefs` re-runs synthesis (→ human re-approval)
on a **monthly schedule + manual trigger** (v1); an **event-driven webhook** (vault git-hook → Hermes
on brand-docs change) is the reserved responsive upgrade. So the Briefs stay current without per-run cost.

### Edge Cases

- Brief not approved → `brand_to_gtm` refuses to spend (no paid run from an unapproved Brief).
- brand-docs missing a field (e.g. no geo) → Brief leaves it null; AutoGTM runs broader, flagged.
- Explee request-body shape differs from the catalog → fail loud, re-check `/public/api/docs` (see 002 note).

## Requirements

### Functional Requirements

1. A Paperclip task synthesizes **two Briefs** (partner, customer) from `brand-docs-final` (Librarian retrieval + Interpreter synthesis) → `Content-Engine/_gtm/brief-partner.md` + `brief-customer.md`.
2. Each Brief is a structured `{companies_filters, people_filters, exclusions, outreach_angle, fit_criteria}` traceable to the docs: persona → `job_titles`/geo/exclusions; positioning → `definition`/industry/`is_b2b`; niche → `criteria`; competitor → exclusions/lookalikes; messaging → `outreach_angle`.
3. Briefs require **human approval** — the vault `.md` is the review surface; only an approved Brief derives to `tenants/tryambakam-noesis/gtm/brief-*.yaml` (the executable payload).
4. `brand_to_gtm(brief)` (deterministic, **TDD'd**) builds the Explee payload from the Brief and runs autogtm via the `explee-proxy` connector; paid ops stay **approval-gated** (002).
5. An **Interpreter re-scoring** pass re-ranks Explee output against the brand differentiators (Kha-Ba-La fit), producing a prioritized list with fit reasons.
6. A Paperclip **routine** `refresh-gtm-briefs` (schedule=monthly + manual `api` trigger for v1; `webhook` trigger **reserved** for event-driven refresh) re-runs synthesis → re-approval.
7. **One parametrized** `brand_to_gtm(brief)` serves both arms — no hard-coded duplication.
8. Tenant-scoped + auditable (#2/#5); the Brief is the interpretation layer before the AutoGTM automation (#3).

### Key Entities

- **Brand GTM Brief** (×2) — `{companies_filters, people_filters, exclusions, outreach_angle, fit_criteria}`; vault `.md` (human source of truth) + derived tenant `.yaml` (executable).
- **`brand_to_gtm`** — Brief → Explee payload → proxy → candidates (deterministic primitive).
- **refresh-gtm-briefs** — Paperclip routine governing the synthesis cadence.

## Success Criteria

- **SC-001**: an AutoGTM run is seeded by a Brief that populates **≥ 6 filter fields** (vs a 1-line scrape).
- **SC-002**: **100%** of paid runs are approval-gated; **0** runs from an unapproved Brief.
- **SC-003**: the re-scored list cites **brand-fit reasons** (not just firmographics).
- **SC-004**: Briefs refresh on cadence with re-approval; **0** stale-Brief autonomous spend.

## Non-Goals (v1)

- Event-driven (webhook) refresh — reserved; v1 is scheduled + manual.
- Reddit / `tn-seed` (003) — separate; this is the GTM-targeting side (they may share the partner output).
- Cold individual outreach — the partner arm targets orgs/channels (brand rule).
- Autonomous spend — every paid run is human-approved.
- Replacing the Explee product UI — the URL-scrape replacement is via the API/Brief, not the product onboarding.

## Resolved Decisions

- **Two Briefs** (Partner + Customer) from one corpus; **one** parametrized `brand_to_gtm(brief)`.
- **Agent synthesizes** (rare, approved) / **API executes** (frequent, deterministic).
- **Brief storage**: vault `_gtm/*.md` (human source of truth) → derived `tenants/.../gtm/*.yaml` (executable).
- **Refresh**: Paperclip routine — **scheduled monthly + manual** (v1); event-driven webhook = the upgrade.
- **Re-scoring**: yes — Interpreter re-ranks vs Kha-Ba-La / positioning fit.

## Constitution Alignment

| # | Principle | How |
|---|---|---|
| 2 | Tenant isolation | Briefs + runs scoped to `tryambakam-noesis`. |
| 3 | Interpretation before automation | the Brief **is** the interpretation; AutoGTM is the automation. |
| 4 | Approval-gated risk | paid Explee ops gated; unapproved Brief can't spend. |
| 5 | Auditability | synthesis + runs are Paperclip tasks/routines, logged. |
| 6 | Wiki as control surface | the vault `_gtm/*.md` Brief is the operator review surface. |

## Resolved (was Open Clarifications)

- **Synthesis runs as a Paperclip agent task** (Interpreter, in-platform) — synthesis is reasoning over
  the corpus, not deterministic. The synthesis prompt + structured-output schema live with the agent.
- **Explee request bodies pinned** from the live OpenAPI 3.1 spec (`/public/api/openapi.json`):
  - `POST /search/companies` → `{ "filters": PublicCompaniesFilters, "page", "page_size" }`
  - `POST /search/people` → `{ "company_filters": PublicCompaniesFilters, "people_filters": PublicPeopleFilters, "page", "page_size" }`
  - `PublicCompaniesFilters` is a **~50-field** object (definition, geo_include/exclude, size, revenue_annual,
    is_b2b/is_saas/is_tech/is_ai, industry_nace_classes, technologies, funding_last_round_stage, criteria,
    has_public_emails, …); `PublicPeopleFilters` = job_titles(+exclude), geo, followers, criteria.
  - **Key insight:** these are exactly what `nl-to-filters` returns → **the Brief _is_ a populated
    `PublicCompaniesFilters` + `PublicPeopleFilters`**, and `brand_to_gtm` passes it straight to
    `/search/companies` + `/search/people` (nl-to-filters becomes an optional bootstrap, not the source).
    The brand-docs populate ~50 fields precisely; a URL scrape populates a handful — that gap is the feature.

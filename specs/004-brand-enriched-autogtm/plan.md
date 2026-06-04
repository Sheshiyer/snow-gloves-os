# Implementation Plan: Brand-Enriched AutoGTM

> Agent **synthesizes** the Brief (rare, reasoning, human-approved); a deterministic, TDD'd primitive
> **executes** AutoGTM from it. The Brief *is* a populated `PublicCompaniesFilters` + `PublicPeopleFilters`
> (the ~50-field Explee ICP), synthesized from `brand-docs-final` instead of a URL scrape.

## Components

1. **Brand GTM Brief** — `{ arm, companies_filters: PublicCompaniesFilters, people_filters:
   PublicPeopleFilters, outreach_angle, fit_criteria, status }`. Vault `Content-Engine/_gtm/brief-{partner,customer}.md`
   (human source of truth) → derived `tenants/tryambakam-noesis/gtm/brief-*.yaml` (executable).
2. **Synthesis** — a **Paperclip agent task**: Librarian retrieves `brand-docs-final` → Interpreter emits
   the two Briefs against a structured-output schema (= the filter objects) → vault, `in_review` for approval.
3. **`scripts/lib/gtm.py` · `brand_to_gtm(brief, *, fetch_json=None)`** (deterministic, TDD'd) — Brief →
   `POST /search/companies {filters}` + `/search/people {company_filters, people_filters}` via the
   `explee-proxy` connector (paid ops approval-gated, 002) → `/enrich/email` → candidates.
4. **Re-scoring** — Interpreter (or `score_fit`) re-ranks candidates vs the Brief's `fit_criteria` +
   brand differentiators (Kha-Ba-La fit) → prioritized list + reasons.
5. **Refresh routine** — Paperclip routine `refresh-gtm-briefs` (schedule=monthly + manual; webhook reserved).

## Data / Contracts

- **Brief** ≈ `nl-to-filters` output + `{ outreach_angle, fit_criteria, arm, status, approved_by }`.
- `brand_to_gtm(brief)` → `{ candidates: [{ company, people, enrichment, explee_relevance }] }`.
- Approval gate: `brand_to_gtm` refuses a Brief whose `status != approved`.

## Delivery Phases

- **A** Brief schema + two hand-authored seed Briefs (partner + customer, populated from brand-docs) + `derive_brief` (approved `.md` → tenant `.yaml`). *(US1)*
- **B** Synthesis agent task — Interpreter prompt + structured-output schema + Librarian retrieval over brand-docs. *(US1)*
- **C** `brand_to_gtm` (TDD: brief → Explee `/search/*` payloads → proxy → candidates; injectable fetch). *(US2)*
- **D** Re-scoring (TDD: rank by `fit_criteria` + differentiators). *(US3)*
- **E** Refresh routine (Paperclip routine; manual + monthly schedule). *(US4)*
- **F** Verify — TDD green; dry-run `brand_to_gtm` on a fixture Brief; approval-gate; route under Dispatcher; `make smoke`.

## Constitution Gates

#2 tenant-scoped · #3 the Brief **is** the interpretation before the AutoGTM automation · #4 paid ops approval-gated + unapproved Brief can't spend · #5 audited (Paperclip tasks/routines) · #6 the vault Brief is the operator surface.

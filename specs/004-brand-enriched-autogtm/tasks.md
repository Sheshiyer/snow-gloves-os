# Tasks: Brand-Enriched AutoGTM

## Phase A — Brief schema + seed Briefs

- [ ] T001 Define the Brand GTM Brief schema (`PublicCompaniesFilters` + `PublicPeopleFilters` + `outreach_angle`/`fit_criteria`/`arm`/`status`)
- [ ] T002 Hand-author seed `Content-Engine/_gtm/brief-partner.md` from the brand-docs (populated filters + exclusions + angle)
- [ ] T003 Hand-author seed `_gtm/brief-customer.md` (Selemene B2B ICP — companies that would license/embed the engines)
- [ ] T004 `derive_brief` (approved `.md` → `tenants/tryambakam-noesis/gtm/brief-*.yaml`) + test (TDD)

## Phase B — Synthesis agent task (Paperclip)

- [ ] T010 Interpreter synthesis prompt + structured-output schema (brand-docs → Brief filter objects)
- [ ] T011 Librarian retrieval config over `brand-docs-final` (persona/positioning/niche/competitor/messaging)
- [ ] T012 Wire as a Paperclip agent task → writes the vault Briefs, sets `in_review` for human approval

## Phase C — brand_to_gtm (TDD)

- [ ] T020 `scripts/lib/gtm.py` · `brand_to_gtm(brief, fetch_json=None)`: brief → `/search/companies {filters}` + `/search/people {company_filters, people_filters}` → `/enrich/email` → candidates
- [ ] T021 `tests/test_gtm.py` (injected fetch; assert the pinned payload shapes + candidate normalization)
- [ ] T022 Approval gate: `brand_to_gtm` refuses a Brief whose `status != approved` (+ test)

## Phase D — Re-scoring (TDD)

- [ ] T030 `score_fit(candidate, brief)` — rank by `fit_criteria` + brand differentiators (Kha-Ba-La), with reasons
- [ ] T031 `tests/test_score_fit.py` (high/low-fit fixtures; reasons present)

## Phase E — Refresh routine

- [ ] T040 Paperclip routine `refresh-gtm-briefs` (schedule=monthly + manual `api` trigger)
- [ ] T041 (reserved) `webhook` trigger on brand-docs change (vault git-hook → Hermes)

## Phase F — Verify + route

- [ ] T050 Dry-run `brand_to_gtm` on a fixture Brief → candidate list (no live spend)
- [ ] T051 Approval-gate test; tenant-scope check; `make smoke` green
- [ ] T052 Register the GTM flow under Dispatcher (hook: `*brand gtm*`, `*enriched gtm*`, `*partner list*`, `*customer icp*`)

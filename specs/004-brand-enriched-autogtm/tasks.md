# Tasks: Brand-Enriched AutoGTM

**Status (2026-06-08):** the deterministic wire is **live + verified** — the brand-docs now drive the GTM ICP end-to-end, no spend. Remaining: the production synthesis-agent automation + the refresh routine.

## Phase A — Brief schema + seed Briefs

- [x] T001 Brand GTM Brief schema → `Content-Engine/_gtm/SCHEMA.md` (frontmatter = `PublicCompaniesFilters` + `PublicPeopleFilters` + `outreach_angle`/`fit_criteria`/`arm`/`status`)
- [x] T002 Seed `Content-Engine/_gtm/brief-partner.md` from brand-docs (12 populated filter fields + exclusions + angle)
- [x] T003 Seed `_gtm/brief-customer.md` — Selemene B2B ICP (companies that would license/embed the engines; 14 filter fields)
- [x] T004 `derive_brief` (approved `.md` → `tenants/tryambakam-noesis/gtm/brief-*.yaml`) + test — in `scripts/lib/gtm.py`, gate-tested

## Phase B — Synthesis agent task (Paperclip)

- [x] T012 Routing registered — Interpreter `gtm-brief-synthesis` hook + `snowgloves:gtm-brief-synthesis` skill (`workflows/skill-hooks.yaml`)
- [ ] T010 Productionize the Interpreter synthesis prompt + structured-output schema (brand-docs → Brief). *Seed Briefs synthesized by-hand as the Interpreter; this automates it.*
- [ ] T011 Librarian retrieval config over `brand-docs-final` (persona/positioning/niche/competitor/messaging)

## Phase C — brand_to_gtm (TDD)

- [x] T020 `scripts/lib/gtm.py` · `brand_to_gtm(brief, call=None)`: brief → `/search/companies {filters}` + `/search/people {company_filters, people_filters}` → candidates
- [x] T021 `tests/test_gtm.py` — injected `call`; pinned payload shapes + normalization (8 tests green)
- [x] T022 Approval gate: `brand_to_gtm` refuses a Brief whose `status != approved` (tested)

## Phase D — Re-scoring (TDD)

- [x] T030 `score_fit(candidate, brief)` + `rank_candidates` — rank by `fit_criteria` (brand/Kha-Ba-La fit), with reasons
- [x] T031 covered in `tests/test_gtm.py` (fit fixtures; reasons present)

## Phase E — Refresh routine

- [ ] T040 Paperclip routine `refresh-gtm-briefs` (schedule=monthly + manual `api` trigger)
- [ ] T041 (reserved) `webhook` trigger on brand-docs change (vault git-hook → Hermes)

## Phase F — Verify + route

- [x] T050 Dry-run `brand_to_gtm` on the seed Briefs → companies+people payloads, no live spend (verified end-to-end)
- [x] T052 Registered under Dispatcher — `brand-enriched-autogtm` hook (`*brand gtm*`, `*enriched gtm*`, `*partner list*`, `*customer icp*`)
- [ ] T051 `make smoke` green in CI (approval-gate + tenant-scope checks; suite is 30/30 locally)

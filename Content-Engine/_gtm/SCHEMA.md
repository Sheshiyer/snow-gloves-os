# Brand GTM Brief — schema (spec 004 · T001)

A **Brand GTM Brief** is a brand-grounded ICP, authored as a markdown file whose **YAML frontmatter is the structured Brief** (the human-readable body is the rationale, traceable to `brand-docs-final`). One Brief per **arm** (`partner` | `customer`).

**The key insight:** the Brief's `companies_filters` / `people_filters` **are** Explee's pinned `PublicCompaniesFilters` / `PublicPeopleFilters` — so `brand_to_gtm` passes them straight to `/search/companies` + `/search/people`. Brand-docs populate ~50 fields precisely; a URL scrape populates a handful. *That gap is the feature.*

## Frontmatter fields

| Field | Type | Read by | Notes |
|---|---|---|---|
| `arm` | `partner` \| `customer` | `brand_to_gtm`, `derive_brief` | which ICP; names the derived `brief-<arm>.yaml` |
| `status` | `in_review` \| `approved` | `brand_to_gtm`, `derive_brief` | **the spend gate** — only `approved` may derive or run a paid Explee call (constitution #4) |
| `companies_filters` | object (`PublicCompaniesFilters`) | `brand_to_gtm` | `definition · geo_include/exclude · size · is_b2b/is_saas/is_tech/is_ai · industry · technologies · funding_last_round_stage · revenue_annual · criteria · has_public_emails …` |
| `people_filters` | object (`PublicPeopleFilters`) | `brand_to_gtm` | `job_titles(+_exclude) · geo · followers · criteria` |
| `exclusions` | string[] | (human + outreach) | brand "avoid" list made operational |
| `outreach_angle` | string | (downstream copy) | how to reach them, in-voice |
| `fit_criteria` | string[] | `score_fit` / `rank_candidates` | brand-fit re-scoring of raw Explee results (≥½ significant words present → met) |

## Lifecycle
```
brand-docs-final ──(Interpreter synthesises)──▶ Content-Engine/_gtm/brief-<arm>.md  (status: in_review)
                                                         │  ◀── human review + approval (set status: approved)
                                                         ▼
derive_brief ─▶ tenants/tryambakam-noesis/gtm/brief-<arm>.yaml  (executable)
                                                         ▼
brand_to_gtm ─▶ Explee /search/companies + /search/people  (approval-gated, via explee-proxy)
                                                         ▼
rank_candidates ─▶ list re-scored by fit_criteria, with brand-fit reasons
```

## Invariants (the spec's success criteria)
- **SC-001** ≥ 6 populated filter fields per Brief (vs a 1-line scrape). *Seeds: partner=12, customer=14.*
- **SC-002** 0 paid runs from an unapproved Brief — `brand_to_gtm` + `derive_brief` raise `PermissionError` unless `status == approved`.
- **SC-003** the re-scored list cites brand-fit reasons, not just firmographics.

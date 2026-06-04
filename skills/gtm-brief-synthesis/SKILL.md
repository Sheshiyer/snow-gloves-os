---
name: "GTM Brief Synthesis"
description: "Synthesize a tenant's Brand GTM Brief (a populated PublicCompaniesFilters + PublicPeopleFilters ICP) from the brand-docs corpus, for brand-enriched AutoGTM. Interpreter + Librarian; writes to Content-Engine/_gtm/ in_review for human approval. USE WHEN refreshing the GTM brief, synthesizing a brand ICP, or before an AutoGTM run."
---

# GTM Brief Synthesis (the agent-synthesizes half · specs/004)

Replaces a thin website scrape with the deep brand corpus → a precise Explee ICP. This is the
**reasoning** half; the deterministic executor (`brand_to_gtm`, `scripts/lib/gtm.py`) is separate.

## Inputs — Librarian retrieval over the tenant's brand-docs
| Doc | Feeds |
|---|---|
| `01-buyer-persona` | `people_filters.job_titles`, geo, exclusions |
| `02-product-positioning` | `companies_filters.definition`, `is_b2b/is_saas/is_tech`, industry |
| `00-niche-validation` | `criteria` |
| `07-competitor-analysis` | `definition_exclude`, lookalike seeds |
| `05-messaging-direction` | `outreach_angle` |
| product / Selemene-engine docs | the **customer** arm's definition |

## Output — one Brief per arm (`partner`, `customer`)

A markdown doc `Content-Engine/_gtm/brief-<arm>.md` whose frontmatter matches
[`brief.schema.json`](./brief.schema.json): `{ arm, status: draft, companies_filters, people_filters,
outreach_angle, fit_criteria, source_docs }`. The two filter objects are **exactly Explee's
`PublicCompaniesFilters` / `PublicPeopleFilters`** (~50 / 6 fields) — populate every field the docs
support, leave the rest `null`.

## Procedure
1. Retrieve the source docs (Librarian).
2. Per arm, synthesize the filter objects + `outreach_angle` + `fit_criteria`, grounded in the docs (cite `source_docs`).
3. Write `brief-<arm>.md` with `status: draft`; set the Paperclip issue `in_review`.
4. **Never self-approve.** A human approves (the spend gate). Only an approved Brief derives to the
   executable tenant `.yaml` (`derive_brief`) and may drive paid Explee ops (constitution #4).

## Brand guard
Partner arm = orgs/channels (never cold individuals). Customer arm = integration-capable B2B.
Honor the brand's anti-goals (no gamification / guru / single-tradition framing) in the angle.

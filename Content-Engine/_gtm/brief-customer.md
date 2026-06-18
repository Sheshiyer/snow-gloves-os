---
arm: customer
status: in_review
tenant: tryambakam-noesis
synthesized_from: tryambakam-noesis/brand-docs-final (product.md → Selemene Engine API · Living Ecosystem)
synthesized_by: Interpreter (snow-gloves 004) — awaiting human approval before any paid run
companies_filters:
  definition: >-
    Wellness, astrology, mindfulness, biohacking and personal-development SOFTWARE companies
    that would license or embed a consciousness-calculation engine — Vedic astronomy, Human
    Design, Gene Keys, biorhythm, tarot, I Ching, numerology, sacred geometry — to add rigorous,
    multi-lens perceptual features (sub-millisecond astronomical calculation, 6 workflows) via API,
    instead of building generic horoscope content.
  geo_include: [US, GB, CA, AU, IE, NL, DE, IN]
  is_b2b: true
  is_saas: true
  is_tech: true
  size: [5, 200]
  industry: [software, wellness, "health & fitness", education, consumer apps]
  technologies: [iOS, Android, "React Native", REST API, GraphQL]
  funding_last_round_stage: [pre-seed, seed, series-a, series-b]
  criteria: >-
    Builds a consumer wellness / astrology / Human-Design / biohacking / personal-development app;
    would embed a calculation or perceptual-lens engine via API; values rigor and depth over
    generic daily-horoscope novelty.
  has_public_emails: true
people_filters:
  job_titles: [founder, "co-founder", ceo, cto, "head of product", "vp product", "product manager", "head of content", "developer advocate", "head of engineering"]
  job_titles_exclude: ["astrologer", "tarot reader", "psychic"]
  geo: [US, GB, CA, AU, IE, EU, IN]
  criteria: >-
    Leads product or engineering at a wellness, astrology, Human Design, biohacking or
    personal-development app that could embed perceptual-lens / calculation APIs.
exclusions:
  - clinical / regulated medical or mental-health software
  - mass-market daily-horoscope entertainment (novelty register, no depth)
  - crypto / NFT / token-speculation products
  - agencies and consultancies (no product to embed into)
outreach_angle: >-
  Embed 16 perceptual lenses — Vedic astronomy, Human Design, Gene Keys, biorhythm, tarot,
  I Ching, sacred geometry — via the Selemene API: sub-millisecond astronomical calculations,
  6 synthesis workflows, an open-source core (github.com/Sheshiyer/Selemene-engine). Differentiate
  your product with "PubMed × Alex Grey" rigor and multi-lens depth instead of generic horoscopes —
  the calculation engine you don't want to build, maintained by the people who designed the lenses.
fit_criteria:
  - builds a consumer wellness, astrology, Human-Design, biohacking or personal-development product
  - would embed or license a calculation / perceptual-lens engine via API
  - values rigor and depth over generic daily-horoscope novelty
  - pre-seed to series-B with budget + roadmap room for differentiating features
---

# B2B Customer ICP — Tryambakam Noesis (license / embed Selemene)

> **Status: `in_review`.** Synthesized from `brand-docs-final` by the Interpreter. A human approves (`status: approved`) before any paid Explee run (constitution #4).

## What's being sold
The **Selemene Engine API** — *"16 mirrors, sub-millisecond astronomical calculations, 6 workflows,"* **Live** at `selemene.tryambakam.space`, source open at `github.com/Sheshiyer/Selemene-engine` (product.md → "The Living Ecosystem"). The B2B-customer arm targets **companies that would license or embed those engines** into their own wellness / astrology / Human-Design / biohacking product.

## Why these filters (traceable to the brand)
- **`definition` + `industry` + `is_saas`/`is_tech`** ← the engines are an **API** (a developer-consumable calculation layer); the customer is a product company that consumes APIs, not a practitioner.
- **`technologies` + `funding_last_round_stage`** ← embedders are app companies (iOS/Android/API) with feature budget — seed-to-series-B is the band that licenses rather than builds from scratch.
- **`outreach_angle`** ← the brand's differentiator: *"precise clinical terminology rendered with visionary artistry … no fantasy terms when the language of biology is more potent"* (PubMed × Alex Grey). Selemene sells **rigor + depth + the open core**, against the generic-horoscope baseline.
- **`exclusions`** ← keep the register: no clinical/regulated medical (the brand makes *"no medical claims"*), no mass-horoscope novelty (wrong depth), no crypto-speculation (despite the soulbound token, the *customer* side is software), no agencies (nothing to embed into).
- **`people_filters`** ← reach the product/eng decision-makers who own "what features ship," not end-practitioners.

## Executes as
On approval → `derive_brief` → `tenants/tryambakam-noesis/gtm/brief-customer.yaml` → `brand_to_gtm(brief)` → Explee `/search/companies` + `/search/people` (approval-gated) → `rank_candidates` by `fit_criteria`. One parametrized `brand_to_gtm` serves both arms (FR7).

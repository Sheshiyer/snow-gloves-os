---
arm: partner
status: in_review
tenant: tryambakam-noesis
synthesized_from: tryambakam-noesis/brand-docs-final (product.md · persona · positioning)
synthesized_by: Interpreter (snow-gloves 004) — awaiting human approval before any paid run
companies_filters:
  definition: >-
    Newsletters, podcasts, practitioner studios and curated communities working in
    consciousness, meta-rationality, depth psychology, Human Design / Gene Keys, Vedic
    and contemplative practice — serving a sophisticated 28–42 self-inquiry audience.
    Channels that can amplify "self-consciousness as technology" to people who have
    already tried the apps and suspect the problem is structural.
  geo_include: [US, GB, CA, AU, IE, NL, DE, IN]
  size: [1, 50]
  is_b2b: true
  industry: [media, publishing, education, wellness, software]
  technologies: [Substack, beehiiv, Ghost, Patreon, "Circle", "Mighty Networks"]
  criteria: >-
    Audience oriented to serious self-inquiry, systems thinking and depth psychology;
    anti-guru, intellectual register; NOT mass-market wellness or manifestation.
  has_public_emails: true
people_filters:
  job_titles: [founder, creator, writer, "podcast host", "newsletter author", practitioner, facilitator, "community lead", editor, essayist]
  job_titles_exclude: ["life coach", "manifestation coach", "abundance coach", "spiritual influencer"]
  geo: [US, GB, CA, AU, IE, EU, IN]
  followers: [5000, 250000]
  criteria: >-
    Writes or speaks on consciousness, meta-rationality, Human Design, Gene Keys, depth
    psychology, Vedanta or somatics for a 28–42 intellectual audience; values rigor and
    sovereignty over wellness optimization.
exclusions:
  - mass-market wellness / self-help
  - manifestation / law-of-attraction / abundance
  - MLM and affiliate-funnel creators
  - generic life-coaching
  - crypto / NFT / token-hype accounts
outreach_angle: >-
  Co-author resonance, do not promote. Offer the Noesis lenses + the open-source Selemene
  engine as a tool your audience can WIELD — anti-guru, treats them as capable. Lead with a
  precise articulation of a structural problem (inherited operating system), not a pitch.
  Cross-pollinate: a guest essay, the 1319 biorhythm-synchronized experience, the open
  Selemene API. Channels target organisations / curated communities, never cold individuals.
fit_criteria:
  - serves a 28–42 serious self-inquiry audience
  - intellectual, anti-guru register (treats the reader as capable, never broken)
  - consciousness, meta-rationality, depth psychology, Human Design or Gene Keys focus
  - values authorship and sovereignty over optimization / hacks / manifestation
---

# Partner / Channel ICP — Tryambakam Noesis

> **Status: `in_review`.** Synthesized from `brand-docs-final` by the Interpreter. A human approves (set `status: approved`) before `derive_brief` / `brand_to_gtm` may run a paid Explee search (constitution #4).

## Who amplifies us
Tryambakam Noesis is found *"not through an ad — through a question."* The partner arm therefore targets **curated resonance points**: creators, newsletters, podcasts and practitioner communities whose audience is the brand's persona — *"somewhere between 28 and 42 … consumed the content, read the books, tried the apps,"* and who *"suspect the problem is structural."* (product.md → "Who This Is For", "How You Find It")

## Why these filters (traceable to the brand)
- **`definition` / `industry` / `technologies`** ← the channels live where serious self-inquiry is written and discussed (Substack/beehiiv/Ghost newsletters, Circle/Mighty-Networks communities, podcasts) — the brand's *"curated resonance points,"* not marketing funnels.
- **`people_filters.criteria` + `fit_criteria`** ← the **Voice** + **Cultural Reference Universe**: Ribbonfarm, Meaningness, Venkatesh Rao (systems thinking); Krishnamurti, Gurdjieff, Watts (anti-guru); Vedanta, Zen, Hermeticism, depth psychology. Partners must share the *anatomist-who-sees-fractals* register.
- **`exclusions`** ← the brand's **Vocabulary "Avoid"** list (journey, healing, manifesting, abundance, hacks, tribe) made operational: no diluted-wellness, manifestation, MLM, or generic coaching channels — wrong audience, wrong register.
- **`outreach_angle`** ← the **Key Principles**: *never position the reader as broken; never promise transformation; success = the reader's independence.* Partner outreach co-authors; it does not convert. **Partner arm targets orgs/channels, never cold individuals** (brand rule, spec Non-Goals).

## Executes as
On approval → `derive_brief` → `tenants/tryambakam-noesis/gtm/brief-partner.yaml` → `brand_to_gtm(brief)` → Explee `/search/companies` + `/search/people` (approval-gated) → `rank_candidates` re-scores by `fit_criteria`.

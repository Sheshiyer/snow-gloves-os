# Tasks: Distribution OS (`tn-seed`)

## Phase A — `_distribution/` scaffold (Content-Engine vault)

- [ ] T001 Create `_distribution/` (`seeding-MOC.md`, `targets/`, `queue/`, `log/`, `_templates/`)
- [ ] T002 Seed `targets/<sub>.md` from the community-seeding guide (Tier-1/2 subs, cadence, best-thread-types)
- [ ] T003 Contribution + X-thread templates in `_distribution/_templates/`
- [ ] T004 Extend `throughput-guardrail` with `seeded_this_week`; surface in `daily-status`

## Phase B — Reddit reader (anonymous JSON)

- [ ] T010 Anonymous Reddit client (`/r/<sub>/new.json` + `/top.json?t=week`, descriptive User-Agent, 429 backoff)
- [ ] T011 Normalize threads (title, body, age, score, comments, permalink)

## Phase C — score + draft

- [ ] T020 Fit scorer (Seeker-Simon signals + best-thread-types + Kha-Ba-La gap; drop wrong-audience tells)
- [ ] T021 Brand-voice drafter (voice-and-tone + the 5 scripts, tailored per thread; soft product reference)
- [ ] T022 Asset matcher (engine cards / Somatic Canticles / posters by theme)
- [ ] T023 X draft-assist (hooks + `THREAD-MATRIX-9x9` / `X-QUOTE-TWEET-LANE`; no discovery)

## Phase D — queue + log

- [ ] T030 Write drafts to `_distribution/queue/<sub>/` with frontmatter, `status: needs-review`
- [ ] T031 On-post: flip `status: posted` + permalink → `log/<YYYY-Www>.md` + response tracker

## Phase E — register in Snow Gloves

- [ ] T040 `skills/tn-seed/` skill (reads the tenant's vault path)
- [ ] T041 Register in `skills/registry.yaml` (interpreter + dispatcher)
- [ ] T042 `skill-hooks.yaml` hook (`*seed*`, `*community*`, `*reddit thread*`, `*distribution run*`)
- [ ] T043 Tenant scope: bind to `tryambakam-noesis` (vault path config)

## Phase F — verify

- [ ] T050 Dry-run on one sub → ≥1 high-fit draft queued (US1)
- [ ] T051 Human-approve loop: never posts; operator post → logged (US1/US3)
- [ ] T052 Brand-guard: no copy-paste / wrong-audience / cold-individual outreach
- [ ] T053 `make smoke` green; route-test the `tn-seed` hook (US2)

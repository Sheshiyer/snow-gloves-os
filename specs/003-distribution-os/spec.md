# Feature Spec: Distribution OS (`tn-seed`) — Content-Engine → Communities, as a Tenant Skill

## Feature Branch

`003-distribution-os`

**Created**: 2026-06-03 · **Status**: Draft

## Goal

De-silo the **distribution last-mile** for the `tryambakam-noesis` tenant: turn approved Content-Engine
content + the community-seeding guide + the 200+ brand assets into a runnable weekly motion that lands
**brand-true contributions in the right communities** — as a governed Snow Gloves skill (`tn-seed`),
not a standalone script.

Fixes the observed gap: Content-Engine *produces* but doesn't *ship* — `blog-to-x` briefs stalled in
`_processing/` ~21 days; the `throughput-guardrail` is Red. `tn-seed` is the missing last mile.

**Decisions locked in brainstorming (2026-06-03):**
- **Extend Content-Engine** (file-based vault pipeline) — don't replace.
- **Agent-assisted, human-approve** — never autopost (brand anti-goal: "AI as gimmick").
- **Channels v1: Reddit (deep auto-discovery) + X (draft-assist)**.
- **Vault-native `_distribution/` layer + an on-demand `tn-seed` skill** (Approach A).

## User Stories

### US1 — Weekly seeding run (Priority: P1)

As the operator, I run `tn-seed` and get brand-voice contribution drafts matched to live, high-fit
Reddit threads (plus X drafts) in a review queue — so I approve/edit/post in minutes instead of
scanning and writing from scratch.

**Independent test**: run `tn-seed`; assert ≥1 draft lands in `_distribution/queue/<sub>/` with
frontmatter (source URL, script used, asset, fit-score, `status: needs-review`), tailored to a real thread.

### US2 — Governed ecosystem node (Priority: P2)

As the ecosystem, `tn-seed` is a Snow Gloves skill (Interpreter for drafting, Dispatcher for the
distribution motion) scoped to the `tryambakam-noesis` tenant — so seeding runs inside orchestration
(tenant-scoped, audited) and can **consume the Explee partner output** from `002`.

**Independent test**: a "seed community contributions" task globs → the `tn-seed` hook; the run is
tagged `snowgloves:tenant:tryambakam-noesis`.

### US3 — Feedback loop (Priority: P3)

As the operator, posted contributions + replies are logged, feeding the seeding guide's Stage-2 signal
and a distribution KPI — so the motion compounds and the throughput guardrail leaves Red.

### Edge Cases

- Reddit rate-limits / down → degrade to "draft from the guide's evergreen thread-types," never block.
- No high-fit thread this week → produce 0 drafts + a note, never force a low-fit contribution.
- Wrong-audience tells in a thread (`"how much does it cost"`) → auto-skip.

## Requirements

### Functional Requirements

1. New `Content-Engine/_distribution/` layer: `seeding-MOC.md`, `targets/` (per-community cadence +
   best-thread-types + last-seeded), `queue/<channel>/` (review tray), `log/<YYYY-Www>.md`, `_templates/`.
2. `tn-seed` discovers via **Reddit public JSON** for Tier-1/2 subs (r/Jung, r/RationalPsychonaut,
   LessWrong-adjacent, …), **scores** (Seeker-Simon signals + the guide's "best thread types" +
   Kha-Ba-La gap; drops wrong-audience tells), **drafts** (voice-and-tone + the 5 scripts, tailored
   per thread, soft product reference), **matches an asset**, and **queues** with `status: needs-review`.
3. **X = draft-assist only** (no free API): drafts from hooks + `THREAD-MATRIX-9x9` / `X-QUOTE-TWEET-LANE`.
4. The human approves **every external word**; the skill **never posts**. On post the operator flips
   `status: posted` + permalink → appended to `log/` + a response tracker.
5. Reuse Content-Engine conventions: `_published/<YYYY-Www>`, the `throughput-guardrail` KPI (extended
   with `seeded_this_week`), the `daily-status` generator.
6. Register `tn-seed` in Snow Gloves: `skills/registry.yaml` (Interpreter + Dispatcher), a
   `skill-hooks.yaml` hook (`*seed*`, `*community*`, `*reddit thread*`, `*distribution run*`), scoped
   to the `tryambakam-noesis` tenant.
7. Brand guard: contribution-first (the guide's #1 rule); never spam/copy-paste; **never cold
   individual outreach**; difficulty-as-filter.

### Key Entities

- **`_distribution/` layer** — targets, per-channel queues, log, templates (extends Content-Engine).
- **`tn-seed` skill** — discover → score → draft → queue → log (on-demand, human-gated).
- **target** — a community profile (cadence, best-thread-types, last-seeded, voice notes).
- **contribution draft** — queued md with source/script/asset/fit-score + review status.

## Success Criteria

- **SC-001**: operator goes "blank → approved drafts" in **< 30 min/week** (vs the current ~21-day stall).
- **SC-002**: `throughput-guardrail` off Red — **≥ 1 seeded contribution/week**.
- **SC-003**: **100%** of contributions human-approved before posting (0 autoposts).
- **SC-004**: **0** copy-paste / wrong-audience contributions (guide red-flags).
- **SC-005**: `tn-seed` runs tenant-scoped + audited like any Snow Gloves skill.

## Non-Goals (v1)

- Autoposting / scheduled autonomous runs (later spec; v1 is on-demand + human-approve).
- X auto-discovery (no free API).
- Paid amplification / ads.
- The Explee partner-finder motion itself (that's `002`; `tn-seed` may *consume* its output, not reimplement it).
- A new web dashboard (vault-native per Approach A).

## Constitution Alignment

| # | Principle | How |
|---|---|---|
| 2 | Tenant isolation | `tn-seed` scoped to `tryambakam-noesis`. |
| 3 | Interpretation before automation | Drafts are proposals; human-gated. |
| 4 | Approval-gated risk | Every external post is human-approved (the gate). |
| 5 | Auditability | `log/` + response tracker + Hermes tags. |
| 6 | Wiki as control surface | The Content-Engine vault IS the operator surface. |

## Resolved Decisions

- **`tn-seed` logic** → a **Snow Gloves skill** (`skills/tn-seed/` in snow-gloves-os) that reads/writes
  the Content-Engine vault directly. The `_distribution/` **data** layer lives in the vault; the
  discover/score/draft/queue/log **logic** lives in snow-gloves. The skill is tenant-scoped to
  `tryambakam-noesis` and configured with the vault path.
- **Reddit discovery** → **anonymous public JSON** (`/r/<sub>/new.json` + `/top.json?t=week`), no
  auth/creds, a descriptive `User-Agent`, and 429 backoff. Sufficient for the weekly 2–3-per-sub cadence.

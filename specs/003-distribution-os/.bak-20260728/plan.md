# Implementation Plan: Distribution OS (`tn-seed`)

> A new tenant-scoped Snow Gloves skill that reads/writes the Content-Engine vault directly. The
> `_distribution/` **data** layer lives in the vault; the discover/score/draft/queue/log **logic**
> lives in snow-gloves. Reddit discovery is anonymous public JSON.

## Components Touched

1. **Content-Engine vault** *(data layer)*
   - New `_distribution/`: `seeding-MOC.md`, `targets/<sub>.md`, `queue/<channel>/`, `log/<YYYY-Www>.md`, `_templates/`.
   - Extend `throughput-guardrail` with `seeded_this_week`; surface in `daily-status`.

2. **Snow Gloves skill** (`skills/tn-seed/`)
   - `discover` — Reddit anon JSON (`/r/<sub>/new.json` + `/top.json`, User-Agent, 429 backoff)
   - `score` — Seeker-Simon signals + guide best-thread-types + Kha-Ba-La gap; drop wrong-audience tells
   - `draft` — voice-and-tone + the 5 scripts, per-thread; soft product reference; asset match
   - `queue` — write to `_distribution/queue/` `needs-review` · `log` — on operator post

3. **Registry & routing**
   - `skills/registry.yaml` (interpreter + dispatcher), `skill-hooks.yaml` hook
     (`*seed*`, `*community*`, `*reddit thread*`, `*distribution run*`), `tryambakam-noesis` tenant scope (vault path).

## Data / Contracts

- `target` — `{ sub, cadence, best_thread_types[], last_seeded, voice_notes }`
- `draft` frontmatter — `{ source_url, sub, script, asset, fit_score, status }`
- KPI `seeded_this_week` — extends the throughput-guardrail Green/Yellow/Red model.

## Delivery Phases

- **A** `_distribution/` scaffold — targets seeded from the community-seeding guide; templates; MOC. *(US1)*
- **B** Reddit reader — anon JSON client (fetch + normalize title/body/age/score/permalink). *(US1)*
- **C** score + draft — fit ranking + brand-voice drafting + asset match (+ X draft-assist). *(US1)*
- **D** queue + log + KPI + daily-status integration. *(US1/US3)*
- **E** register `tn-seed` in Snow Gloves (registry/hooks/tenant scope). *(US2)*
- **F** verify — dry-run on one sub; human-approve loop; brand-guard; `make smoke`.

## Constitution Gates

#2 tenant-scoped · #3 drafts are proposals (human-gated) · #4 human approves every post · #5 log + Hermes audit · #6 the vault is the control surface.

---
name: "tn-seed (Distribution Seeding)"
description: "Community-seeding distribution for a tenant: discover high-fit threads, draft brand-voice contribution briefs (human-approve, never autopost), and queue them for review. Tenant-scoped; reads the Content-Engine _distribution vault. USE WHEN seeding communities, running a distribution run, or reddit-thread outreach."
---

# tn-seed — Distribution Seeding

The distribution last-mile for a Snow Gloves tenant. Reads the tenant's
`Content-Engine/_distribution/` vault, discovers high-fit threads, scores them
(Seeker-Simon signals + best-thread-types; drops wrong-audience tells), drafts a
brand-voice contribution **brief** (script + Kha-Ba-La gap + asset), and writes it to
`_distribution/queue/<sub>/` as `needs-review`. **It never posts** — the human approves
every external word.

## Run

```bash
python3 scripts/tn_seed.py --tenant tryambakam-noesis [--fixture listing.json] [--min-fit 0.5]
```

## Pipeline

`fetch_threads` (anon JSON; OAuth adapter pending — Reddit 403s anonymous) → `score_thread`
→ `build_brief` → `write_brief`. Code: `scripts/lib/{reddit,score,draft,seed}.py`.
Tested: `tests/test_{reddit,score,draft,seed,targets}.py`.

## Routing

Registered under the **Dispatcher** (distribution motion); the **Interpreter** assists with the
draft wording. Hook: `community-seeding` (globs `*seed*`, `*community*`, `*reddit thread*`,
`*distribution run*`).

## Brand guard

Contribution-first; never copy-paste; never cold individual outreach; difficulty-as-filter.

# NotebookLM pitch deck — exact prompt

Verbatim prompt fed to `notebooklm generate slide-deck` on 2026-05-18.
Re-running this with the same sources should produce an equivalent deck.

```
Create a 10-12 slide pitch deck for a NON-TECHNICAL stakeholder.
Goal: explain Snow Gloves OS — a 'Hand-In-Glove' business operations platform — in 5 minutes.
Structure:
(1) Title — Snow Gloves OS / Hand-In-Glove Business Operations Platform;
(2) The problem — running a business feels like playing piano with oven mitts on;
(3) The metaphor — hand=business, glove=Snow Gloves, snow=calm frictionless ops;
(4) The four reusable engines — Connector, Knowledge, Interpretation, Orchestration;
(5) The life of an event — webhook → verify → audit → route → agent → task created;
(6) The 7-agent team — CEO, CTO, Chief of Staff, Librarian, Interpreter, Dispatcher, Sentinel;
(7) Skill orchestration — Chief of Staff routes 60 skills via glob-matched hooks;
(8) Tenant isolation — one runtime, many businesses, strict data separation;
(9) The self-improving loop — Sentinel sweeps audit log daily into agent EVOLUTION.md;
(10) The constitution — 7 principles (spec-before-code, tenant-isolation-first, etc.);
(11) What you actually run — make doctor, make tenant-new, make app-dev;
(12) Closing — Ready to glove your business? Repo + onboarding wizard CTA.
Tone: confident, calm, premium, like Stripe or Linear. Avoid jargon. Use plain English analogies.
```

## Settings used
- `--format detailed`
- `--length default`
- `--retry 2`

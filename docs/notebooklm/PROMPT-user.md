# NotebookLM — new-user kit (not a pitch)

Verbatim prompt for `notebooklm generate slide-deck` and sibling artifacts.
Audience: someone who will **use** Snow Gloves this week. Do not describe how the product was designed, Spec-Kit, the constitution, or the engineering process.

```
Create a 10-12 slide deck for a new operator who will use Snow Gloves OS this week.
Goal: they can install, pick their agent, onboard one company, and know what a quiet week looks like.
Do NOT talk about how the product was built, specs, constitutions, or contributor workflows.

Structure:
(1) Title — Snow Gloves OS / You keep the decisions;
(2) What it is — a senior team that drafts; you send, spend, and publish;
(3) First hour — install, pick a runtime, interview, one skill;
(4) Install — clone, install.sh, optional desktop wizard; 0.2.0 is a new app, reinstall from 0.1.x;
(5) Pick a runtime — Cursor, Claude, Codex, Hermes, Grok, or generic; the product writes into that seat;
(6) The interview — plan mode, one question at a time, FILL: when a fact is missing, never guess;
(7) The harvest — snowgloves-harvest.md, apply, enable one add or pointer card;
(8) The seven desks — CEO, CTO, Chief of Staff, Librarian, Interpreter, Dispatcher, Sentinel as jobs, not architecture;
(9) Modules — add / pointer / hold / refuse; hold and refuse cannot be turned on; risky sends wait;
(10) A quiet week — drafts wait, only crossed lines speak, Sentinel at the end of the day;
(11) Approvals — spend, public post, personal data, legal: one yes;
(12) Closing — wiki URL and the product repo. Start with one job.

Tone: calm, plain English, like a colleague walking you through the first Monday. No jargon. No "we built" story.
```

## Settings

- Slides: `--format detailed --length default --retry 2`
- Audio: `notebooklm generate audio` with the same audience instruction
- Video: `notebooklm generate video` whiteboard/explainer; same audience
- Briefing: `notebooklm generate report --format briefing-doc`

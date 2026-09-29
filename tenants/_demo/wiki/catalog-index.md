# _demo catalog index

Chief-of-Staff and Librarian entrypoint for dry-run knowledge ingest (no auto-install).

## Field Theory

- Articles: `~/.fieldtheory/library` (markdown via ingest `include_glob`)
- Taste skill packs: `~/.fieldtheory/library/taste/skills/**/SKILL.md` (catalog only)
- Bookmark jsonl: **not** ingested — Hermes/FT cache remains external SoT

## Vault ecosystem (copied)

- [X bookmark harvest receipt](ecosystem/HARVEST-2026-09-29.md)
- [Ecosystem candidates](systems/ecosystem-candidates.md) — Four-Signal decisions
- [Skill hook crosswalk](systems/skill-hook-crosswalk.md) — pointer / refuse / hold only

## Reference catalog

- [founders-kit index](systems/founders-kit-index.md) → `vendors/founders-kit/` (pin: `vendors/founders-kit.pin`)

## Creative (vault markdown only)

- [IG saved harvest](creative/ig-harvest.md)
- [Hands pointers](systems/hands-pointers.md)

## Operator

```bash
python3 scripts/ingest.py _demo
# review tenants/_demo/ingest-plan.json
SNOWGLOVES_EMBED_BACKEND=stub make embed T=_demo
```

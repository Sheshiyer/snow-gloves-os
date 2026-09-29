# Knowledge ingest receipt — 2026-09-29

| Field | Value |
|-------|-------|
| Tenant | `_demo` |
| Backend | `stub` (`SNOWGLOVES_EMBED_BACKEND=stub`) |
| Ingest | `python3 scripts/ingest.py _demo` |
| Plan gate | Founder review of `ingest-plan.json` before embed |

## Sources wired

- `~/.fieldtheory/library` (markdown, size cap)
- `~/.fieldtheory/library/taste/skills` (`SKILL.md`)
- `vendors/founders-kit` (pinned submodule)
- `tenants/_demo/wiki`

## Non-goals honored

No bookmark jsonl ingest, no glam media, no Vectorize, no auto-install.

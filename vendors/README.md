# Vendored reference catalogs

Third-party markdown catalogs pinned for Snow Gloves tenant ingest. Not agent skills and not auto-installed runtimes.

## Policy

- MIT or equivalent permissive license only.
- Pin commits in `<name>.pin`; bump only after founder review.
- Ingest via `tenants/<slug>/sources.yaml` and `scripts/ingest.py` — never cookies, secrets, or sync daemons inside this repo.
- Do not add hooks in `workflows/skill-hooks.yaml` without a separate Four-Signal founder pick.

## Catalogs

| Vendor | Path | Pin file | Role |
|--------|------|----------|------|
| — | — | — | **founders-kit** moved off-repo (2026-09-29); use Mac reference pin + FT harvest |

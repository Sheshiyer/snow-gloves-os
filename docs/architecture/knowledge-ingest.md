# Knowledge ingest architecture

Snow Gloves loads **read-only filesystem paths** into a tenant-scoped embedding index. No sync daemons, cookies, or auto-install inside this repo.

## Flow

```
tenants/<slug>/sources.yaml
        ↓
scripts/ingest.py  →  tenants/<slug>/ingest-plan.json  (founder review)
        ↓
scripts/embed_worker.py  →  tenants/<slug>/vector-index.jsonl
        ↓
agents/librarian  (retrieval)
```

## sources.yaml extensions

Optional per source (backward compatible):

| Field | Purpose |
|-------|---------|
| `include_glob` | Allow only matching paths (e.g. `**/*.md`, `**/SKILL.md`) |
| `exclude_glob` | Skip paths (e.g. `**/node_modules/**`, `**/.git/**`) |
| `max_file_bytes` | Skip oversized files; reason recorded in `skipped` |

`ingest-plan.json` includes `files[]` and `skipped[]` with reasons.

## External inputs (_demo dry-run)

| Input | Path | Notes |
|-------|------|-------|
| Field Theory library | `~/.fieldtheory/library` | Markdown only; not bookmark jsonl |
| FT taste packs | `~/.fieldtheory/library/taste/skills` | `SKILL.md` catalog |
| founders-kit | `vendors/founders-kit` | Pinned submodule; **ReferenceCatalog** |
| Tenant wiki | `tenants/_demo/wiki` | Vault harvest copies |

Sync for FT and glam stays on the founder Mac outside Snow Gloves.

## founders-kit role

MIT tools/playbooks directory ([avinash201199/founders-kit](https://github.com/avinash201199/founders-kit)). Ingested markdown is for Librarian/CoS reference — **not** registered in `workflows/skill-hooks.yaml` without a Four-Signal founder pick.

## Non-goals

- Cookie stores, bookmark `.jsonl`, glam media trees
- Cloudflare Vectorize / Hermes Cortex mutation
- `npx skills`, ClawHub, or MCP auto-install
- EC2 `ft sync` from this pipeline

## Operator

```bash
make doctor
python3 scripts/ingest.py _demo
SNOWGLOVES_EMBED_BACKEND=stub make embed T=_demo
```

Implementation repo for this path: `snow-gloves-os-modular` (Hermes bus naming). Live Mac tree may still use SG Bus until reconciled.

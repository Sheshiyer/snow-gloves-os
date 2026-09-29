# Knowledge ingest architecture

Snow Gloves loads **read-only filesystem paths** into a tenant-scoped embedding index. No sync daemons, cookies, or auto-install inside this repo.

**Tenant product only:** ingest paths must live under the tenant (e.g. `tenants/<slug>/wiki`). Field Theory, `~/.fieldtheory/library`, and founders-kit are **external** to Snow Gloves — harvest on the founder Mac and reference via the vault, not `sources.yaml`.

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

## External inputs (out of scope for SG ingest)

| Input | Where it lives | Notes |
|-------|----------------|-------|
| Field Theory library | Founder Mac `~/.fieldtheory/library` | `ft sync` / `ft md` — not SG `ingest.py` |
| founders-kit | Founder Mac reference git pin | MIT catalog; not `vendors/` in this repo |
| Bookmark jsonl | `~/.fieldtheory/bookmarks/` | Never ingested here |

Sync for FT and glam stays on the founder Mac outside Snow Gloves.

## founders-kit role (external)

MIT tools/playbooks directory ([avinash201199/founders-kit](https://github.com/avinash201199/founders-kit)). Use as a **category index** on the Mac; Librarian may see tenant wiki copies only. **Not** registered in `workflows/skill-hooks.yaml` without a Four-Signal founder pick.

## Non-goals

- Cookie stores, bookmark `.jsonl`, glam media trees
- Cloudflare Vectorize / Hermes Cortex mutation
- `npx skills`, ClawHub, or MCP auto-install
- EC2 `ft sync` from this pipeline
- Founder `~/.fieldtheory` or `vendors/founders-kit` in `sources.yaml`

## Operator

```bash
make doctor
python3 scripts/ingest.py _demo
SNOWGLOVES_EMBED_BACKEND=stub make embed T=_demo
```

Implementation repo for this path: `snow-gloves-os-modular` (Hermes bus naming). Live Mac tree may still use SG Bus until reconciled.

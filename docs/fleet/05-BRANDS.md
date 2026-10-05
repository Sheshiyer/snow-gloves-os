# 05. Brands

A brand is a tenant. `tenants/<slug>/` holds everything a wing may know about one brand: `MANIFEST.yaml` (identity, isolation, portfolio position), `sources.yaml` (where the brand's documents live), `context/` (the seven files a runtime reads), `enabled.yaml` (which modules the founder switched on; absent means nothing is enabled), and `approvals/` (tickets). Isolation is `strict` for every brand: no brand reads another brand's folder, and cross-brand sharing is explicit, named and approved by the founder.

Brand tenants are instance data. They live in the private data checkout named by `SNOWGLOVES_DATA` (`$SNOWGLOVES_DATA/tenants/<slug>/`), never in this repository, which keeps only the fixtures (`_demo`, `acme`, `tryambakam-noesis`). The real portfolio (brands, parents, projects, the founder's open questions) is in `snow-gloves-ops/docs/fleet/05-BRANDS.md`.

A brand's position in the portfolio is a block in its manifest, added after the scaffold (which is otherwise untouched):

```yaml
portfolio:
  root: <portfolio-root-slug>
  parent: <parent-slug>     # null for the portfolio root itself
brand:
  domain: <domain>          # FILL until known
  status: planning_not_provisioned
```

The `status: active` line at the top of a manifest is the scaffold default written by `scripts/tenant_new.sh`; it means the folder is live for planning, not that the brand is provisioned.

## How a wing mounts brands

A wing (one Mac mini profile; see the other files in `docs/fleet/`) mounts brands with `scripts/fleet/node_profile.py`, delivered by `specs/007-fleet-wings/`:

```bash
export SNOWGLOVES_DATA=/path/to/snow-gloves-ops   # where the brand tenants live

# enable every registered tenant on the wing
python3 scripts/fleet/node_profile.py enable --all-tenants --node <wing>

# render one brand for one runtime on that wing
python3 scripts/fleet/node_profile.py render --tenant <slug> --node <wing> --runtime <rt>
```

Runtimes are the adapters in `adapters/<rt>/adapter.yaml` (claude, codex, cursor, opencode, grok, hermes, muse, openclaw, generic). `render` is a dry run until `--write`. Most adapters write into the runtime's own paths (`{project}/CLAUDE.md`, `{project}/AGENTS.md`, `{home}/...`); the `generic` adapter and any `--out` render land under `tenants/<slug>/runtime/`, which is gitignored because renders are per machine. Re-render after pulling instead of committing them.

## How brand context reaches the runtime

The wing render (`node_profile.py render`, not the plain `onboard.py --render-adapter`) writes a marked rules block into the runtime's rules file (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/snowgloves.mdc`, whichever the adapter names) and a `render.json` receipt at `tenants/<slug>/runtime/<wing>/<rt>/render.json`. The block carries a "Brand context" list that links `tenants/<slug>/context/voice.md`, `offer.md`, `customer.md`, and `company.md` when they contain real text, meaning any line beyond the heading, the `Source:` line, and `FILL:` lines (`scripts/onboard.py`: `CONTEXT_LINKS`, `has_real_text`, `context_links_for`; the list is written by `scripts/lib/adapters.py`). A file that holds only FILL lines is not linked. An unfilled brand file whose only prose is its status line ("nothing recorded; agents must not draft public copy") still counts and is linked, so the agent reads the stop instruction. Filling those four files with sourced facts is therefore what makes a wing brand-aware; nothing else carries brand facts into the agent.

The other three files have fixed jobs: `owner.md` names the approver and the send rule, `proof.md` holds what may be cited, and `open-questions.md` collects every FILL line from the other six so the founder can answer them in one pass.

Rules for writing the files: write only what a source backs and cite the source path; write `FILL: <specific question>` for anything else; never invent a brand fact; never put credentials in the folder.

## Knowledge path

1. Put the brand's document paths in `tenants/<slug>/sources.yaml`. `tenants/tryambakam-noesis/sources.yaml` shows the shape: `id`, `type: filesystem`, `path`, `note`; `include_glob` narrows to markdown as `tenants/_demo/sources.yaml` does.
2. `python3 scripts/ingest.py <slug>` walks the sources and writes `tenants/<slug>/ingest-plan.json`.
3. `make embed T=<slug>` runs `scripts/embed_worker.py` (NVIDIA `nv-embedqa-e5-v5` per `config/snowgloves.yaml`) and writes the tenant-scoped index `tenants/<slug>/vector-index.jsonl`; the chunk cache lands in `tenants/<slug>/_embed_cache/` (gitignored).

A brand source that lives outside the data checkout (a brand guide, a design-system folder) is linked from `sources.yaml` by path and never copied in; the facts it carries are summarised, with the path cited, in the tenant's `context/` files.

## Guardrails

- The founder is the approver for every brand; each `context/owner.md` says so.
- No external send without an approved ticket in `tenants/<slug>/approvals/`: public post, email, DM, SMS, money, hiring or personal data, legal commitments (`skills/connector-gate/SKILL.md`, step 5).
- Nothing is enabled until `tenants/<slug>/enabled.yaml` exists (`python3 scripts/onboard.py --tenant <slug> --enable <id>`). Approval-gated modules (ads, cold email, SMS, PR, influencer outreach) are marked `approval: 'yes'` there.
- `tests/test_tenants_hygiene.py` keeps whatever `tenants/` folder is in use consistent (the fixtures here, or the data checkout when `SNOWGLOVES_DATA` is set): every directory under `tenants/` is registered in `_registry.yaml`, no registry entry lacks a folder, no slug is listed twice, every manifest names its directory (`tenant: <slug>`), and no `context/*.md` is empty. Portfolio-specific checks (parents, retired brands) live with the data in the private repo.

# 05. Brands

A brand is a tenant. `tenants/<slug>/` holds everything a wing may know about one brand: `MANIFEST.yaml` (identity, isolation, portfolio position), `sources.yaml` (where the brand's documents live), `context/` (the seven files a runtime reads), `enabled.yaml` (which modules the founder switched on; absent means nothing is enabled), and `approvals/` (tickets). Isolation is `strict` for every brand: no brand reads another brand's folder, and cross-brand sharing is explicit and named (`specs/006-editorial-steward-integration/portfolio-map-proposal.json`, `desk_policy`).

## Portfolio

The parent column comes from `specs/006-editorial-steward-integration/portfolio-map-proposal.json` and `docs/PORTFOLIO-ORG-MAP.md`. The founder confirmed every parent on 2026-10-05 (`specs/006-editorial-steward-integration/founder-intake-2026-10-05.md`): SaveWatt was dropped, and iVerif became a project under CEE Management, so both tenant folders were removed. Legal ownership is not inferred: `legal_entity` is `null` for every branch, and the proposal's rule reads "Repository location does not imply ownership."

| Slug | Display name | What it does (founder, 2026-10-05) | Parent | Sources present? |
|---|---|---|---|---|
| `axtech` | Axtech | portfolio root; sells through the Axtech shop | none (portfolio root) | no (FILL) |
| `heyzack` | HeyZack | home automation | `axtech` | partial: external brand PDF skill, linked not copied; vault path FILL |
| `ecoled` | Ecoled | B2B / B2C (sketch) | `axtech` | no (FILL) |
| `kartezzi` | Kartezzi | FILL | `axtech` | no (FILL) |
| `izzimo` | Izzimo | FILL | `axtech` | no (FILL) |
| `wave-concept` | Wave | B2B mobile accessories | `axtech` | no (FILL) |
| `sunfeed` | Sunfeed | renovation, construction; installs heat pumps, plumbing, electrical | `axtech` | no (FILL) |
| `cee-management` | CEE Management | CEE eligibility and processing with the obligé | `axtech` | no (FILL) |
| `china-sourcing` | China Sourcing | vendor network curation; routes purchase intent for a margin | `axtech` | no (FILL) |
| `metagration` | Metagration | AI website, calling and answering for restaurants, hotels, parlours | `axtech` | no (FILL) |
| `axio` | AXIO | Metagration's B2B AI wing with on-site training | `metagration` | no (FILL) |

Projects live inside a tenant, not in their own folder (`projects` in the proposal):

| Project | Parent tenant | What it is |
|---|---|---|
| `axtech-shop` | `axtech` | storefront for all products sold under the group's brand names, heat pumps included |
| `safvr-channel` | `axtech` | pitch safvr.com's safety management and video intelligence to B2B companies and for pilots |
| `iverif` | `cee-management` | the system CEE Management uses to process CEE documents |

Cross-brand flows are proposed in `cross_brand_flows` and are not approved: the heat-pump chain, the shop reading brand catalogs, and China Sourcing routing purchase intent. Until the founder approves one, no tenant reads another's folder.

Status is `brand.status` in each `MANIFEST.yaml`; every brand is `planning_not_provisioned`. The `status: active` line at the top of the manifest is the scaffold default written by `scripts/tenant_new.sh` and means the folder is live for planning; it does not mean the brand is provisioned. The other entries in `tenants/_registry.yaml` (`acme`, `tryambakam-noesis`, `mathis`, `_demo`) are not brands in this portfolio.

The manifest block that records the position (added after the scaffold, which is otherwise untouched):

```yaml
portfolio:
  root: axtech
  parent: axtech        # null for axtech itself; metagration for axio
brand:
  domain: heyzack.ai    # FILL for the others
  status: planning_not_provisioned
```

## How a wing mounts brands

A wing (one Mac mini profile; see the other files in `docs/fleet/`) mounts brands with `scripts/fleet/node_profile.py`, delivered by `specs/007-fleet-wings/`:

```bash
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

HeyZack's only source today is the brand PDF skill at `/Users/sheshnarayaniyer/.claude/skills/HeyZackBrandPdf/` (typeface Brinnan, the blue/pink/ink palette, the white logo). It is linked from `tenants/heyzack/sources.yaml` with `include_glob: ["**/*.md"]` and must not be copied into this repository. The facts it carries are already summarised, with the path cited, in `tenants/heyzack/context/voice.md`.

## Guardrails

- The approver is the founder for every brand (`specs/006-editorial-steward-integration/organization.json`, `human_approver: founder`); each `context/owner.md` says so.
- No external send without an approved ticket in `tenants/<slug>/approvals/`: public post, email, DM, SMS, money, hiring or personal data, legal commitments (`skills/connector-gate/SKILL.md`, step 5).
- Nothing is enabled until `tenants/<slug>/enabled.yaml` exists (`python3 scripts/onboard.py --tenant <slug> --enable <id>`). Only `heyzack` has one: written on 2026-10-02 by `scripts/onboard.py`, 57 modules, 13 of them approval-gated (`approval: 'yes'`, including ads, cold email, SMS, PR and influencer outreach).
- `tests/test_tenants_registry.py` keeps the registry, manifests, portfolio blocks, and context files consistent: every directory under `tenants/` is registered, every manifest names its directory, the eleven brand tenants carry `portfolio` and `brand` blocks, every parent matches the proposal, the retired `savewatt` and `iverif` folders stay gone, and no `context/*.md` is empty.

## Founder FILL list

Answer once; each item names the file that receives the answer.

Parents: answered on 2026-10-05 (`specs/006-editorial-steward-integration/founder-intake-2026-10-05.md`). Still open from the sketch (write into `context/company.md` of the tenant named):

- `axtech`: the "C…lia?, OEM content" box, its name and where it belongs.
- `heyzack`: what "Symphonie Électricité?" under HeyZack is.
- `ecoled`, `sunfeed`, `cee-management`: what the numbers 25 and 6 and the note "500R" mean.
- `wave-concept`: is the trading name "Wave" or "Wave Concept"?
- `axio`: an uncommitted 2026-09-30 interview on the Coding Mac described Axio as lead generation via getleads.io; is that still part of AXIO?

Domains (`brand.domain` in `MANIFEST.yaml`): every brand except HeyZack. Only `heyzack.ai` is recorded.

Vault paths (`sources.yaml`):

- all eleven: the vault path to the brand documents (positioning, offer, voice, visual identity)
- `heyzack`: the path to `heyzack/brand-system` (tokens, BRAND-GUIDE.md, DESIGN.md), which the PDF skill says it was derived from

Legal entities (`context/company.md`): the proposal records `legal_entity: null` for Axtech and every branch. Confirm each, and whether Axtech trades directly or only through branches.

Everything else is listed per brand in `tenants/<slug>/context/open-questions.md`.

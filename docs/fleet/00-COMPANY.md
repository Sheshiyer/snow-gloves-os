# 00. Company: who operates, who owns, who is served

Read this before touching a machine. It fixes the names used in `fleet.yaml`, `tenants/` and the
rest of `docs/fleet/`.

## Operator

**Thoughtseed Private Limited** operates the fleet: it owns the Apple Account, the Tailscale
tailnet, the three Mac minis in the Paris office and the authoring seat. `fleet.yaml` records this
as `company`. Operating a brand's agents is not the same as owning the brand (next section).

## Portfolio

Axtech is the operational portfolio root (`portfolio_root: axtech` in `fleet.yaml`). The branches
with a source-backed parent come from `specs/006-editorial-steward-integration/` and
`docs/PORTFOLIO-ORG-MAP.md`:

| Tenant slug | Name | Parent | Source |
|---|---|---|---|
| `axtech` | Axtech | (root) | specs/006 organization.json |
| `heyzack` | HeyZack | axtech | specs/006 portfolio-map-proposal.json |
| `ecoled` | Ecoled | axtech | specs/006 portfolio-map-proposal.json |
| `kartezzi` | Kartezzi | axtech | specs/006 portfolio-map-proposal.json |

Four more brands get tenants but have **no source-backed parent yet**. The founder completes this
table; until then their `parent` stays `FILL` in [05-BRANDS.md](05-BRANDS.md) and nothing is
inferred from where a repo lives or who signs in.

| Tenant slug | Name | Parent | Legal entity | Completed by |
|---|---|---|---|---|
| `izzimo` | Izzimo | FILL | FILL | founder |
| `iverif` | Iverif | FILL | FILL | founder |
| `savewatt` | Savewatt | FILL | FILL | founder |
| `wave-concept` | Wave Concept | FILL | FILL | founder |

The rule, quoted from `specs/006-editorial-steward-integration/spec.md`: "Axtech is the
operational root; legal ownership is not inferred." And from `docs/MAC-MINI-NODE-ONBOARDING-PLAN.md`:
"Do not infer brand ownership or permissions from a shared Apple login." A tenant folder is an
operating scope, not a cap table.

## Which wing serves which brand

All wings serve all brands. A brand is a tenant under `tenants/<slug>/`; a wing is a machine
profile under `nodes/<wing>/`. Step 7 of the [README](README.md) enables every tenant on every
wing. What differs per wing is the kind of work and the tools installed, not the list of brands.

| Wing | Hostname / overlay | Operator user | Always on | Serves |
|---|---|---|---|---|
| marketing | `marketing-mac` | `sg-marketing` | no | all brands |
| design | `design-mac` | `sg-design` | no | all brands |
| coding | `coding-mac` | `sg-coding` | yes (hosts OmniRoute, Hermes) | all brands |

## Desks to wings: a proposal, not a fact

`specs/006` defines four desk templates, all with `status: proposed`: editorial,
creative-production, delivery, growth. They were written for branch scoping, not for machines.
They map naturally onto the function split, and the mapping is offered here as a starting
assumption for [03-MACHINE-PROFILES.md](03-MACHINE-PROFILES.md), to be confirmed when the first
real jobs run:

| Desk template (specs/006) | Responsibility (quoted) | Proposed wing |
|---|---|---|
| editorial | "Branch-specific content planning and review" | marketing |
| growth | "Branch campaign preparation; paid calls and delivery approval-gated" | marketing |
| creative-production | "Branch-specific media preparation and asset receipts" | design |
| delivery | "Branch project execution" | coding |

Two cautions carried over from specs/006: desks are assigned "only after branch/project
resolution", and "shared definitions do not share sources, credentials, budgets, senders or approval
authority". A desk running on the Marketing Mac for HeyZack sees HeyZack's tenant, not Ecoled's.

## Control roles

The seven Snow Gloves control roles in `AGENTS.md` (ceo, cto, chief-of-staff, librarian,
interpreter, dispatcher, sentinel) are reusable definitions instantiated per tenant. They run on
whichever wing a job lands on; they are not pinned to a machine. Events still reach the Chief of
Staff through Hermes on the Coding Mac.

## What this page does not decide

- Legal entities and ownership links (founder intake; see the FILL table).
- Budgets, senders and connector permissions per brand (tenant `enabled.yaml` and approvals).
- Whether a fourth machine or a second gateway is ever needed ([DECISIONS.md](DECISIONS.md)).

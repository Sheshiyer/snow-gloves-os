# Company

Source: `specs/006-editorial-steward-integration/portfolio-map-proposal.json`, `docs/PORTFOLIO-ORG-MAP.md`, `docs/AXTECH-REMOTE-WORKSPACE-DRAFT.md`.

- Axtech is the portfolio root in the Snow Gloves portfolio map: `portfolio.id: axtech`, `parent: null`, `legal_entity: null` (`specs/006-editorial-steward-integration/portfolio-map-proposal.json`).
- Operating branches named by the proposal: HeyZack, Ecoled, Kartezzi. Each is `relationship: operating_branch`, `legal_entity: null`, `status: planning_not_provisioned`, sourced from `docs/AXTECH-REMOTE-WORKSPACE-DRAFT.md`.
- Legal ownership is not inferred. The proposal's rule: "Admit projects only beneath a named Axtech branch after source-backed intake. Repository location does not imply ownership." `docs/PORTFOLIO-ORG-MAP.md` adds that legal company names, exact ownership links and branch project inventories remain source-backed intake decisions.
- Desk policy (proposal): instances scoped per branch and project; cross-branch data access by explicit named sharing only; no automatic grants.
- Activation recorded by the proposal: `tenant_provisioned: false`, `cloud_agent: false`, `public_delivery: false`. This tenant folder was scaffolded on 2026-10-02 as a planning placeholder and does not change that.
- `docs/AXTECH-REMOTE-WORKSPACE-DRAFT.md` (2026-09-30, proposal only) describes the owner intent: operate Snow Gloves OS remotely on Mac minis and run campaign operations across Axtech brands, initially HeyZack, Ecoled and Kartezzi.

FILL: legal entity name, registration country, and registration number for Axtech.
FILL: does Axtech trade under its own name, or only through its branches?
FILL: Axtech domain (`brand.domain` in `MANIFEST.yaml`).
FILL: are there branches beyond HeyZack, Ecoled and Kartezzi? The proposal's branch project inventory is listed as unresolved.

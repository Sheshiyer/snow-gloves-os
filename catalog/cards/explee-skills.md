---
id: explee-skills
name: Explee GTM skill pack
category: skills
kind: skill-pack
disposition: add
repo: "https://github.com/Sheshiyer/explee-skills"
source: "catalog-core-descope"
risk: high
approval: yes
agents: [dispatcher]
hooks: [dispatcher.gtm-and-prospecting, dispatcher.brand-enriched-autogtm]
runtimes: [any]
summary: "Optional Explee orchestrator + spokes. Paid search/enrich/autogtm wait for approval. Not core routing."
---

# Explee skills

Optional module. Dispatcher GTM globs still exist; they do not list `explee:*` on the core graph. Enable this pack (and the `explee_proxy` G-Stack connector) when a tenant wants live prospecting. Paid ops stay approval-gated.

## Provenance

- Former core `dispatcher` registry entries and `skill-hooks.yaml` gtm/brand-enriched hooks
- Connector remains in `connectors/g-stack/capabilities.yaml` as `explee_proxy`

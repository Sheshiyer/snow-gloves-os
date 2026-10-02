# Owner

Source: `specs/006-editorial-steward-integration/organization.json` (`human_approver: founder`), `skills/connector-gate/SKILL.md`.

Approver: the founder (repository owner). Every decision that leaves this tenant's folder goes to the founder first.

Rules every agent follows for `wave-concept`:

- Never send anything externally without an approved ticket in `tenants/wave-concept/approvals/` (`scripts/approvals.py`). This mirrors `skills/connector-gate/SKILL.md` step 5: a public post, or an email, DM, or SMS to anyone outside the company, always needs approval before the call, whatever the module card says. The same holds for money (spend, invoices, payroll, ads, paid API calls), hiring or personal data, and legal commitments.
- Use an external tool only when `tenants/wave-concept/enabled.yaml` lists it. The file does not exist yet, so nothing is enabled for this tenant.
- Credentials never go in this folder, in `enabled.yaml`, or in a rules file.
- Do not infer legal ownership or brand facts from repository names or folder locations (`specs/006-editorial-steward-integration/portfolio-map-proposal.json`, `project_rule`).

FILL: owner name and the channel the founder wants approval requests on for Wave Concept.
FILL: is there a second approver for Wave Concept (brand lead), or only the founder?

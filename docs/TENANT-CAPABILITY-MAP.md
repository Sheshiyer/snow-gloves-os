# Tenant capability map

Open the town's Field Kit and select **Neighborhoods**. Each tenant card has a
**Skills, agents and connections** disclosure. It reads the selected operations
data root; the public fixture mode does not read the private operations checkout.

The map joins configured module IDs from the tenant's `enabled.yaml` to the
platform catalog. Disposition, risk, approval and applicable roles come from the
catalog. Unknown, held and refused IDs stay held. A high-risk module requires
approval even when its catalog approval flag says `no`.

Assigned tenant agents are separate from the seven reusable control roles and
the business preparation templates. A template's presence does not instantiate
an agent. Connection selection does not establish authentication. Registered
source IDs and admission flags do not establish completed ingestion.

Missing, malformed, foreign-tenant or unsafe configuration is shown as missing or
held. An older snapshot without a capability map shows **Unavailable**, rather
than implying an empty configuration. File reads are bounded and reject symlink
components, duplicate keys and YAML aliases. The client validates the projection
before rendering it.

Existing brand planning continues to show parent, projects, desks and proposed
flows. Optional private owner-context corrections live in
`specs/006-editorial-steward-integration/tenant-reconciliation.json`; their
`context_only` authority changes display evidence, never module, identity or
runtime permissions. Stable tenant identifiers remain visible when a current
display name differs. Pending planning conflicts stay visible.

For a full private portfolio review, start an isolated loopback workspace with
an explicit private data root. Preserve any tenant pin on a running fleet API.
Do not route an unpinned private portfolio API through an existing public proxy.
An authenticated SSH forward for the operator should bind its local listener
to `127.0.0.1`.

Useful verification commands:

```sh
python3 -m pytest tests/test_cockpit_tenant_map.py tests/test_cockpit_snapshot.py tests/test_cockpit_brand_summary.py tests/test_cockpit_acceptance.py tests/test_infra_cockpit.py -q
npm --prefix apps/infra-block test -- src/tenant-map.test.ts src/ops-client.test.ts src/brand-summary.test.ts
npm --prefix apps/infra-block run build
```

Large JSON snapshots negotiate bounded gzip responses for clients that accept it.
The original raw-response size limit and client timeout remain unchanged.

These verify source contracts. An actual browser check and installed-host
readback are separate evidence gates.

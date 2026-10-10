# Fleet business context (source contract)

This is a source-level, read-only preparation contract for the existing fleet
task graph. It does **not** add a scheduler, CRM, database, connector,
tenant-admission path, or live ERP capability. The ERP may contain CRM data and
product reconciliation may be in progress, but this repository does not claim
that any referenced record, product, price, or availability has been read.

The existing control plane remains unchanged:

- exactly seven logical control roles (`ceo`, `cto`, `chief-of-staff`,
  `librarian`, `interpreter`, `dispatcher`, `sentinel`);
- at most seven children per root task;
- one worker execution slot;
- business preparation is always `read`, including where code-write tasks are
  otherwise configured.

`catalog/business-roles.json` contains 19 reusable, tooling-agnostic templates.
They have no live-tool grants. A template's `control_owner` is descriptive
routing metadata; `domain_role` never grants a control role, write permission,
connector permission, or external-effect authority.

## Strict context schema

`business_context` is optional for ordinary development tasks. When supplied,
it is an object with schema `snowgloves.business-context.v1` and exactly these
required fields, plus optional `catalog_revision`:

```json
{
  "schema": "snowgloves.business-context.v1",
  "domain_role": "commercial-secretary",
  "instance_ref": "erp-synthetic-01",
  "record_type": "opportunity",
  "record_id": "record-synthetic-01",
  "dossier_id": "dossier-synthetic-01",
  "source_revision": "source-synthetic-r1",
  "catalog_revision": "catalog-synthetic-r1"
}
```

The example deliberately uses only synthetic identifiers. ERP fields are
opaque bounded references, not URLs, paths, SQL, queries, credentials, or
record contents. Unknown fields (including requester-supplied readiness) are
rejected. Tenant and organization continue to come only from authoritative
project configuration.

A context task is stored as `commercial-preparation`; that category requires a
valid context, and a context cannot use a different category. Development
submission without context retains its existing behavior.

## Server admission and catalog readiness

The private coordinator's project configuration must explicitly opt into
business context before the coordinator invokes Hermes. The public shape below
is illustrative only; it is **not** a service configuration to copy into this
repository:

```json
{
  "business": {
    "instance_refs": ["erp-synthetic-01"],
    "record_types": ["opportunity", "dossier"],
    "domain_roles": ["commercial-secretary", "cctp-analyst", "estimator"],
    "readiness": {
      "revision": "catalog-synthetic-r1",
      "reconciliation_status": "pending",
      "evidence_ref": "catalog-evidence-synthetic-r1"
    }
  }
}
```

`readiness` is server configuration, never model or requester attestation. Its
only supported status values are `pending` and `verified`. A context may bind a
`catalog_revision`; it cannot say that the catalog is reconciled.

Pending product reconciliation still permits non-price preparation such as
commercial secretary intake, requirements analysis, and marketing planning.
The registry marks `estimator`, `buyer`, `sales-follow-up` and `finance-admin`
as price-dependent. These templates, and any future price-dependent template, requires a server snapshot with
`reconciliation_status: "verified"` and an exact matching
`catalog_revision`. The coordinator checks this both at submission and again
immediately before a worker claim. A changed snapshot leaves a stale
price-dependent task unclaimed; it does not create a new price or availability
claim. Status and graph responses expose `business_gate.dispatch_ready` and a safe
hold reason if current server evidence prevents dispatch. The persisted lifecycle
remains queued; the hold is derived, without adding a second scheduler.

This gate applies to the declared template. It does not semantically classify
arbitrary text hidden in another template's brief. All business tasks remain
read-only drafts, with missing evidence explicit and independent content review
required before any commercial use.

## CLI and task graph

The client accepts a context file and can set its domain role without adding a
top-level authority field:

```sh
python3 scripts/fleet_tasks.py --token-file /path/to/founder.token submit \
  --project synthetic-project \
  --brief "Prepare a source-linked intake draft" \
  --context-file ./business-context.json \
  --domain-role commercial-secretary
```

`--domain-role` requires `--context-file`. If the file already has a different
`domain_role`, the CLI rejects the conflict. The coordinator remains the final
validator; a context file does not admit an instance, record type, role, or
tenant.

Children of a business root inherit the immutable ERP/dossier/source/catalog
scope. They may select another admitted template by sending a complete context
with the same immutable references, while normal seven-role and stage checks
still apply. A retry must preserve the complete context and template. A child
cannot add context to a development parent, remove a business parent's context,
or turn business preparation into a CTO write task.

## Hermes, worker, and evidence boundaries

For a validated business task, the coordinator sends the normalized context to
Hermes using only the bounded `commercial-preparation` category. Hermes can
return only its existing seven-role `logical_role` plus a summary. It cannot
change the context, category, project, root, access, or authorization; the
coordinator compares the returned scope to its own validated value.

The worker receives the registry mission, normalized context, and current
server readiness snapshot inside a delimited untrusted-data block. The prompt
states `erp_access: "unverified"` and forbids connector calls, SQL execution,
writes, external effects, and fabricated ERP data. The worker independently
rejects a malformed business assignment or one carrying write access.

Successful business artifacts include only safe provenance references:
`domain_role`, sanitized `business_context`, the server readiness snapshot, and
`erp_access: "unverified"`. They are not ERP extracts and do not prove ERP read
access. Live connector configuration, credential handling, deployment, and
runtime availability evidence remain outside this source contract.


A child may omit `--context-file` and `--category` to inherit its parent's
business context. Catalog revision is immutable even when absent: an intake
graph without a catalog revision cannot acquire one later. Start a new graph
with the reviewed revision after reconciliation. References matching configured
coordinator credentials reject rather than being redacted into a different ID.

# Bounded Chief-of-Staff role fanout

The fleet coordinator can create one bounded, read-only development plan beneath
an existing root task. It is intentionally separate from task submission,
Hermes interpretation, and any ERP or commercial workflow.

## Admission

Fanout is default-off. The coordinator admits `POST /v1/tasks/<root-id>/fanout`
only when both configuration grants are present:

```json
{
  "projects": {
    "example": { "fanout": true }
  },
  "principals": {
    "founder": { "fanout_projects": ["example"] }
  }
}
```

The request body may be empty and accepts no options. It requires the root
task's owner credential; worker credentials cannot submit, plan, cancel, or
otherwise administer work. The SSH-friendly equivalent is:

```sh
scripts/fleet_tasks.py fanout <root-id>
```

Only an authorized `development` root can be fanned out. It cannot be a nested
task, a cancelled/cancel-requested/failed/interrupted root, or a root that
already has manual children. Every automatic child inherits the root owner,
project, and runtime and is permanently `access: read`. This operation neither
enables write work nor grants business, ERP, connector, credential, node, or
filesystem access.

Once a fanout plan exists, that root rejects every new manual child in the same
SQLite transaction. The sole exception is an ordinary, bounded retry whose
`supersedes` chain resolves to an original planned member and still matches its
read-only role and stage; it keeps that member's plan position. Roots without a
fanout plan retain the existing manual-only graph behavior.

## Planning boundary

After coordinator authorization and scope checks pass, the coordinator calls
the existing authenticated loopback Hermes bridge at `POST /plan`. The bridge
uses the pinned Hermes revision, isolated profile, empty toolset, safe mode,
and reviewed local gateway route already used by `/interpret`.

The bridge receives only the authorized root brief plus the fixed seven roles
and five stages. It returns JSON with exactly:

```json
{
  "children": [
    {
      "logical_role": "librarian",
      "stage": "reference",
      "title": "Collect bounded references",
      "brief": "..."
    }
  ]
}
```

There must be two through seven children, all roles must be unique, and the
final child must be `sentinel` at `verify`. A title is at most 200 characters
and a planner child brief is at most 4,000 characters. Unknown fields,
unknown roles/stages, duplicate roles, a missing/finally-invalid Sentinel, and
any requested `access` or other authority field reject the entire plan. Both
the bridge and coordinator validate this contract independently. Hermes has no
database, worker, scheduler, root, runtime, credential, connector, or
permission authority, and no substitute plan is created when it is unavailable.

## Durability and execution

The coordinator stores one plan, its ordered assignments, and its child tasks
in one SQLite transaction before returning a response. It also records a
`chief_of_staff_plan_accepted` audit event on the immutable root reference.
Repeating the operation returns the stored plan and child IDs without another
model call. Concurrent callers may both reach the planner before commit, but
the unique root plan and transaction reread prevent duplicate child creation.

Automatic children reuse the existing single-slot worker and lease machinery.
They are eligible only after:

1. the root has succeeded with a checksum-verified artifact; and
2. each earlier automatic child has succeeded, in durable plan order.

Failed, interrupted, or cancelled prerequisites leave later automatic children
queued with a derived `hold_reason` in task detail and graph responses.
Retries retain the existing bounded child retry behavior and remain in the
same plan position. Manual children retain their existing graph semantics.

On claim, an automatic child receives its validated role/stage plus only
coordinator-verified, relative-path SHA-256 references to the completed root
and prior plan artifacts in the same owner/project scope. The worker validates
that metadata before creating a worktree, gives the model a fixed read-only
role prompt with delimited untrusted brief/context, and records role, stage,
parent, and source references in its result artifact. References are opaque
provenance metadata; they do not cause artifact reading or knowledge ingestion.
Before a reference is propagated, the coordinator rechecks artifact
containment and checksum, then parses its JSON envelope and requires its
`task_id` and `attempt_id` to match the selected completed task attempt.
Missing, malformed, changed, or foreign envelopes hold downstream planned
children rather than supplying a reference.

The graph's existing `verified` status remains a derived execution/artifact
condition. Metadata-only source references do not prove Sentinel substantive
verification or any stronger semantic validation.

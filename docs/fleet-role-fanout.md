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

`artifact_context` is a separate, default-off project boolean. It has no effect
outside an admitted automatic fanout plan. To opt a project into bounded
predecessor-result delivery, retain the two admission grants above and set:

```json
{
  "projects": {
    "example": { "fanout": true, "artifact_context": true }
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

On claim, every automatic child receives its validated role/stage plus
coordinator-verified, relative-path SHA-256 `source_artifacts` references to
the completed root and prior plan artifacts in the same owner/project scope.
This is the compatibility mode when `artifact_context` is absent or `false`:
the references stay opaque provenance metadata and do not cause the worker to
open, ingest, or claim knowledge from an artifact.

With `artifact_context: true`, the coordinator re-reads the same contained,
checksum-verified bytes before every dependency claim. It parses the JSON
envelope with duplicate-key rejection, requires its `task_id` and `attempt_id`
to match the selected completed attempt, and extracts only a nonblank string
`output` no larger than **4,096 UTF-8 bytes**. It sanitizes all configured
coordinator principal, worker, and Hermes tokens before attaching the bounded
values as `source_outputs` alongside the unchanged `source_artifacts`.
Each output contains only `task_id`, `attempt_id`, and `output`; it never
contains an artifact path, checksum, envelope, or other artifact payload.
The plan bound limits a claim to at most seven source outputs.

Malformed JSON, a changed checksum, foreign task/attempt binding, a missing or
non-string output, blank output, and oversized output leave the downstream
automatic child queued with a visible dependency hold. No stale or cached
artifact output is reused after a failed recheck.

Before model launch, the worker validates that `source_outputs` has exactly
the same ordered task IDs and count as `source_artifacts`, validates every
attempt ID and output bound, and rejects any extra or malformed shape. It
never resolves a supplied artifact path. The fixed read-only prompt keeps
checksum references separate and embeds only the verified outputs in a clearly
delimited **untrusted JSON task-data** section. Neither the output, the brief,
nor any reference can authorize tools, paths, writes, connectors, credentials,
or other capabilities. The worker independently redacts its own credentials
before prompting the model. Its result artifact records
`source_context_mode` as `metadata-only` or `verified-output`, retains only
the `source_artifacts` metadata, and never copies `source_outputs` or a full
predecessor artifact into the result.

The graph's existing `verified` status remains a derived execution/artifact
condition. Source-context delivery, including a Sentinel prompt with bounded
predecessor output, does not prove Sentinel substantive verification or any
stronger semantic or live validation.

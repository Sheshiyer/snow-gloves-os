# Fleet catalog execution and application clients

The coordinator is the sole authenticated task authority. The web board and the
stdio fleet MCP server use the same project scopes, task IDs, events, approval
records and verified artifacts. No connector is activated by viewing its card.

## Capability readiness

`GET /v1/context` returns authorized projects, supported runtimes, configured
workers and caller permissions. Worker `availability: observed` means an
authenticated worker polled within twice its lease duration (minimum 30 seconds,
maximum 300). It is an observation of polling, not boot, provider, build or
execution acceptance. `unobserved` workers remain visible in context.

`GET /v1/capabilities` returns every catalog card, connector and connector action
for each authorized project. Each row has `id`, `name`, `project`, `tenant`,
`state`, `reason`, and an `input_schema` when its reviewed skill adapter loads.

| State | Meaning |
|---|---|
| `refused` | The catalog is hold/refuse or explicitly non-enableable, even if tenant YAML was edited |
| `disabled` | No valid tenant activation, or caller lacks submit permission |
| `missing_configuration` | Reviewed source, digest pin or schema is invalid/missing |
| `unsupported` | No reviewed adapter, unsupported kind/runtime, or no observed eligible worker |
| `approval_required` | Other gates pass; exact action needs separately granted approval |
| `executable` | Current source, activation, scope, schema and worker observation pass |

Tenant activation comes only from `tenants/<configured-project-tenant>/enabled.yaml`
through `SNOWGLOVES_DATA` and the `snowgloves.enabled.v1` schema. Caller-provided
tenant names, commands, roots and arbitrary task templates are rejected.

## Reviewed execution registry

`catalog/execution-registry.json` is a source-reviewed registry, separate from
catalog presence and instance activation. Its schema is
`snowgloves.capability-registry.v1` and `entries` is keyed by catalog action ID.
Missing entries never execute. A `reviewed_skill` entry declares:

```json
{
  "adapter": "reviewed_skill",
  "skill_path": "skills/example/SKILL.md",
  "skill_sha256": "<64-character lowercase SHA256 of reviewed source>",
  "runtime": "codex",
  "approval_required": false,
  "input_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {"focus": {"type": "string", "maxLength": 1000}},
    "required": ["focus"]
  }
}
```

Only skill-kind catalog cards can use this adapter. The source must resolve inside
this checkout's `skills/`, must match its pinned digest, and must fit the bounded
read-only task brief. Inputs are limited to declared string/integer/boolean
properties, required fields, enum values and scalar limits. Unknown input fields
and unsupported schema features fail closed. Input JSON remains untrusted task
data and cannot authorize tools, paths, credentials, network access or writes.

This initial adapter queues a read-only development analysis through the normal
worker and OmniRoute runtime. It does not enable paid calls, messages, installations
or external connector operations. G-Stack's checked-in auth binding module is a
stub; its presence is not a real connector read contract. Connector actions
remain unsupported until an actual reviewed adapter and credential contract are
implemented and independently verified. A model-written claim is not connector
proof.

## Execution and approval interfaces

`POST /v1/capabilities/execute` accepts exactly:

```json
{
  "project": "authorized-project",
  "capability_id": "catalog-id",
  "inputs": {"focus": "documentation"},
  "idempotency_key": "stable-client-submission-id",
  "worker_id": "optional-configured-worker-id",
  "approval_id": "optional-approved-action-id"
}
```

The response is `{task, request_digest}`. A worker selector uses `worker.id` from
context, not a hostname, node path or executable. Omitted selectors retain normal
scheduling. Normal `POST /v1/tasks` also accepts this bounded selector; it becomes
part of task idempotency and is enforced during claiming.

`POST /v1/approvals` accepts the same action fields without `approval_id` and only
creates a pending record. `GET /v1/approvals` returns scoped rows containing the
requester `owner`, project, tenant, capability ID, safe inputs, optional worker,
request digest, status, decision identity and consumed task. It does not return
credentials or server paths.

`POST /v1/approvals/<id>/approve` and `/reject` take an empty JSON object. The
`approve` permission must be explicitly granted; legacy defaults stay
`read`, `submit`, `cancel`. Identity comes from the authenticated principal.
Approval authority is project-scoped and does not grant task-submission authority.
Do not grant `approve` to the Grok Bot application principal.

The coordinator binds approval to requester, project, configured tenant,
capability, exact inputs, selected worker, adapter pin and catalog policy. It
rechecks activation, permission and readiness when approving and dispatching.
Creating a task, recording its idempotency mapping and consuming approval happen
inside one SQLite write transaction. One approved action creates at most one task;
the same successful submission key returns that task. Changed inputs, another
requester, another project, changed policy/source, or a second submission key cannot
reuse it. Cancelled, interrupted or failed tasks do not restore consumed approval.
Uncertain execution remains in the existing interrupted/recovery path, with no
automatic replay.

## Artifacts and MCP

`GET /v1/tasks/<id>/artifact` checks read permission, task scope, succeeded state,
stored digest, bounded JSON, and the task/attempt/project/runtime/node envelope.
It returns `{artifact: {sha256, content}}`, where `content` is safe parsed JSON.
The digest identifies stored verified bytes; current credential redaction can
change display content, so it is not a downloadable-byte checksum. Artifacts are
limited to 512 KiB through this interface. Older local artifacts lacking project
identity remain inaccessible through it; existing task receipts are preserved.

The stdio MCP adapter adds `fleet_context`, `fleet_capabilities`, `fleet_artifact`,
`fleet_execute_capability`, `fleet_approvals`, `fleet_request_approval`,
`fleet_approve` and `fleet_reject`, retaining existing task tools. It remains a thin
loopback HTTP client. Use a dedicated application token and the app's supported
MCP configuration. Application token registration and real app tool-discovery are
separate installation acceptance from these source tests.

## Verification

`tests/test_fleet_capabilities.py` covers denied activation/disposition/scope,
strict input validation, source pins, observed worker readiness, selected-worker
claiming, concurrent approval consumption, durable submission retry, stale leases,
artifact identity/hash/scope and secret redaction. `tests/test_fleet_mcp.py` covers
thin HTTP delegation and server tool registration when MCP is installed. These
checks do not certify live domains, macOS boot recovery, physical power restoration
or a real India-team session.

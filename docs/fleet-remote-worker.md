# Remote fleet workers

Remote enrollment is an **explicit, bounded artifact protocol** for a worker
that has its own checkout and reaches the coordinator through SSH forwarding.
It does not share the coordinator database, the coordinator artifact directory,
or a project filesystem mount.

This document describes source configuration shapes only. Keep real
configuration, node tokens, gateway keys, SSH host policy, and service
supervision in the private operations checkout.

## Enrollment contract

Both ends must opt in:

1. The coordinator's credential for the worker has
   `"remote_artifacts": true` and a stable credential-bound `"node_id"`.
2. The worker's private configuration has `"remote_artifacts": true` and
   maps every eligible project ID through `"project_roots"`.

A remote credential without a valid `node_id` is rejected by coordinator
configuration validation. A worker mapping is rejected unless its resolved
local root is exactly one of that worker's `allowed_roots`.

Remote workers default to `access_modes: ["read"]`. The coordinator skips jobs
outside those capabilities before assigning a lease. Enabling `"write"` also
requires the existing project/principal write grants and worker write-root and
verification configuration. Legacy local workers retain their existing modes.

Coordinator credential example:

```json
{
  "workers": {
    "coding02": {
      "token": "REMOTE_WORKER_TOKEN",
      "projects": ["snowgloves"],
      "runtimes": ["codex"],
      "access_modes": ["read"],
      "remote_artifacts": true,
      "node_id": "coding02"
    }
  }
}
```

Remote worker example:

```json
{
  "endpoint": "http://127.0.0.1:4101",
  "token": "REMOTE_WORKER_TOKEN",
  "node_id": "coding02",
  "state_root": "/private/ops/runtime/coding02-worker",
  "remote_artifacts": true,
  "allowed_roots": [
    "/private/projects/snow-gloves-os"
  ],
  "project_roots": {
    "snowgloves": "/private/projects/snow-gloves-os"
  },
  "codex_path": "/absolute/path/to/codex",
  "git_path": "/usr/bin/git",
  "gateway_url": "http://127.0.0.1:20128/v1",
  "gateway_key_file": "/private/ops/runtime/gateway.key",
  "model": "noesis-fast"
}
```

`project_roots` is an identity-to-local-root map, not a path supplied by the
coordinator. In remote mode the worker ignores `root` and `artifacts_root`
fields even if a forged assignment includes them. A claimed task has a
`project` identity and `remote_artifacts: true`; the worker rejects a project
that is absent from its local map.

A project served only by enrolled remote workers may omit `projects.<id>.root`
from the coordinator configuration. If any legacy/local worker can run that
project, its existing coordinator-side Git-root requirement remains in force.

## Transport boundary

The coordinator remains bound to `127.0.0.1`, and a remote worker only accepts
an endpoint of the form `http://127.0.0.1:<port>`. The OmniRoute gateway remains
exactly `http://127.0.0.1:20128/v1`. Do not replace either with a LAN,
Tailscale, wildcard, or public bind.

The remote host therefore uses reviewed SSH forwarding that exposes local
loopback endpoints, conceptually:

```text
remote worker 127.0.0.1:4101  --SSH forward--> coordinator 127.0.0.1:4101
remote worker 127.0.0.1:20128 --SSH forward--> gateway     127.0.0.1:20128
```

For example, the private operations runbook can establish forwards with local
bind addresses such as `-L 127.0.0.1:4101:127.0.0.1:4101` and
`-L 127.0.0.1:20128:127.0.0.1:20128`. The worker does not manage SSH,
credentials, or tunnel lifecycle; loss of the forward follows the existing
lease/reconciliation behavior.

## Artifact protocol and bounds

Local workers keep the existing artifact-file report:

```json
{
  "path": "/coordinator/artifacts/task-attempt.json",
  "sha256": "..."
}
```

An enrolled remote worker instead reports a successful result as inline,
authenticated content:

```json
{
  "content": "{\"attempt_id\":\"...\",\"node\":\"coding02\",\"project\":\"snowgloves\",\"task_id\":\"...\", ...}",
  "sha256": "sha256-of-the-UTF-8-content"
}
```

The decoded inner JSON envelope includes at least:

```json
{
  "task_id": "assigned-task-id",
  "attempt_id": "assigned-attempt-id",
  "project": "assigned-project-id",
  "node": "credential-node-id",
  "runtime": "codex",
  "output": "redacted runtime result"
}
```

The worker serializes this compactly and computes the digest over its UTF-8
bytes. It limits the inner artifact to **24 KiB**. If ordinary runtime prose is
the only oversized field, it is shortened with a visible
`[TRUNCATED FOR REMOTE ARTIFACT BOUND]` marker. A large patch or other
non-output structure is rejected rather than silently omitted.

The coordinator accepts at most **64 KiB** for any JSON HTTP request, rejects
duplicate JSON keys, malformed UTF-8, excessive nesting, and overly large
inline artifacts before durable processing. The worker likewise refuses to
send an oversized request or consume an oversized coordinator response.

## Coordinator acceptance sequence

For a remote `succeeded` report, the coordinator performs these checks in this
order:

1. Authenticate the worker token.
2. Match the currently assigned worker, its project scope, task ID, attempt
   ID, and the current lease token.
3. Return an existing result for a duplicate event ID **before** handling
   artifact bytes.
4. Confirm that the task is still active and not cancelling.
5. Check the inline byte limit and reported SHA-256 digest.
6. Decode the inner JSON and match task, attempt, project, runtime, and the
   credential's `node_id`.
7. Redact the current lease, all configured credential strings and credential-like values from
   persisted JSON.
8. Generate a coordinator-owned filename and atomically write the redacted
   artifact inside the coordinator artifact directory.
9. Record the event and terminal task state in the coordinator transaction.

The client never supplies a destination path. The stored artifact digest
describes the persisted, canonical redacted JSON. The submitted digest is still
verified first against the original transmitted content; when redaction changes
the content, these two digests intentionally differ.

The global coordinator capacity remains one active task. Remote enrollment
does not add a scheduler, database, mount, or parallel execution slot.

## Operational limitations

- This is a source-level protocol, not SSH provisioning or a deployment
  mechanism. Create and supervise SSH forwards only through the private
  operations runbook.
- Remote writes remain isolated in the remote worker's disposable worktree.
  Remote credentials default to `access_modes: ["read"]`; enabling remote
  writes requires a separate explicit `"access_modes": ["read", "write"]`
  coordinator decision plus the worker's existing local write/test gates.
  Their resulting artifact, including any patch, must fit the remote artifact
  limit; nothing is written into a coordinator checkout.
- A lost lease, cancellation, invalid digest, stale attempt, cross-worker
  report, or malformed envelope is rejected and requires the existing manual
  reconciliation path.
- Enrollment is configuration-bound: changing a worker name, token, project
  scope, or node ID requires coordinated private configuration changes on both
  sides. There is no dynamic worker discovery.

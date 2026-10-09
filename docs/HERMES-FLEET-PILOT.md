# Hermes fleet coordinator pilot

The pilot uses separate coordinator (loopback 4101), Hermes interpreter bridge
(loopback 4102), and one worker process. The coordinator owns task state and
assignment leases; Hermes does not receive database or worker administration
credentials. The existing event bus remains distinct from this durable task API.
Other Macs need a worker and tested runtime adapters, not a second scheduler.

## Configuration and startup

Keep configuration and keys in the private operations checkout, never in this
repository. All JSON config files and gateway key files must have mode `0600`;
state directories should have mode `0700`. These examples contain placeholders.

Worker configuration:

```json
{
  "endpoint": "http://127.0.0.1:4101",
  "token": "WORKER_TOKEN",
  "node_id": "mac-coding-1",
  "state_root": "/private/ops/runtime/worker",
  "allowed_roots": ["/private/projects/snow-gloves-os"],
  "artifacts_root": "/private/ops/runtime/coordinator/artifacts",
  "codex_path": "/absolute/path/to/codex",
  "git_path": "/usr/bin/git",
  "gateway_url": "http://127.0.0.1:20128/v1",
  "gateway_key_file": "/private/ops/runtime/gateway.key",
  "model": "noesis-fast",
  "poll_seconds": 2,
  "job_timeout": 300
}
```

Bridge configuration:

```json
{
  "token": "BRIDGE_TOKEN",
  "hermes_root": "/Users/axio/.hermes/hermes-agent",
  "hermes_python": "/absolute/path/to/hermes/python",
  "hermes_revision": "93257fd315751ae119886457bb8e1c46a162406c",
  "hermes_profile": "snowgloves",
  "gateway_url": "http://127.0.0.1:20128/v1",
  "gateway_key_file": "/private/ops/runtime/gateway.key",
  "model": "noesis-fast"
}
```

Run `python3 scripts/fleet_worker.py --config /private/worker.json` and
`python3 scripts/fleet_hermes_bridge.py --config /private/bridge.json` under
separate reviewed launch agents. Their health checks and logs are independent.
Back up existing Hermes configuration before creating the named `snowgloves`
profile; do not overwrite existing account credentials.

The bridge verifies the installed Hermes Git revision. In the same Python
process it registers `snowgloves-none`, asserts that its resolved tool list is
empty, and starts the installed Hermes CLI with that explicit toolset and safe
mode. An empty CLI `--toolsets` value is unsafe: this Hermes revision substitutes
default tools. Safe mode excludes user customizations, MCP servers, plugins and
rules; the named profile isolates persisted sessions. Explicit `custom` provider,
model and gateway environment select the routed endpoint without native fallback.

## Interfaces and authority

The bridge accepts authenticated `POST /interpret` with `title`, `brief`,
`project` and optional `category: development`. Its result preserves the caller's
original task content and identity, adding only a validated seven-role
`logical_role`, sanitized `summary` and pinned `hermes_revision`. Model output
cannot change project, credentials, filesystem root or dispatch permissions.
`GET /healthz` reports bridge health. Requests require a local Host, prohibit
browser Origins, cap bodies at 64 KiB, and never return raw runtime failures.

The worker uses authenticated `POST /v1/worker/claim` and
`POST /v1/worker/report`. Reports contain task/attempt identity, lease token,
unique event ID and one of heartbeat/log/succeeded/failed/interrupted/cancelled.
Worker credentials cannot submit tasks or administer the fleet. The pilot has
one managed execution slot; independently started developer sessions consume
resources but are not scheduler-managed work.

Each Codex attempt runs in a new detached worktree from the allowed repository's
HEAD, with `--ignore-user-config`, an explicit OmniRoute Responses route and
`--sandbox read-only`. This first capability reviews code and produces an
artifact; it does not enable arbitrary coding writes, deployment, messaging or
connector mutations. Native Codex configuration remains separate. Changes to
write-capable execution require an explicit capability and acceptance tests.

Private raw CLI JSONL stays on the worker. The shared event feed receives status
metadata, not raw runtime output. A successful run must yield a final agent
message. Its redacted result is written to the allowed artifact directory with
a SHA-256 digest; the coordinator independently verifies that digest.

## Recovery and evidence

The worker is a separately supervised process, so closing SSH leaves execution
running. It heartbeats while the CLI runs, handles cancellation by terminating
the CLI process group, and continues through a brief coordinator restart.
Persisted terminal reports retry with the same event ID without re-execution.
If the worker restarts with uncertain prior execution, it reports interruption
and writes `recovery-required.json`; an operator must reconcile process and task
state before removing that hold. Rejected/stale leases are held similarly.
There is no automatic replay of uncertain effects or cross-Mac session migration.
Retain worktrees and private logs for investigation rather than deleting dirty
working copies. Gateway credentials are never included in reports or artifacts.

Tests in `tests/test_fleet_execution.py` use fake runtimes to verify the explicit
route, artifact digest/redaction, root restrictions, pending report retry,
interrupted recovery, cancellation and bridge authentication/output validation.
They do not establish installed Hermes/Codex compatibility or physical mini
acceptance. Record a real event-to-artifact round trip, SSH disconnect/reconnect,
coordinator restart, failure behavior, restore and scheduled reboot separately.
Launch agents run in the selected logged-in user context. FileVault unlock and
before-login availability require physical-device evidence; SSH persistence is
not proof of unattended cold-boot recovery.

## Private UI transport

A reviewed UI may be exposed through private Tailscale Serve while its UI, API,
coordinator and bridge remain bound to loopback. Configure the UI with
`SNOWGLOVES_UI_ALLOWED_HOSTS` as a comma-separated list of exact hostnames.
Set `SNOWGLOVES_COCKPIT_PORT` to the selected loopback projection API port.
The cockpit CLI accepts repeated `--allowed-origin https://exact-ui-host`
arguments; the coordinator has a separate exact `allowed_origins` list.
Never disable Host validation or introduce wildcard Origins for remote access.

The browser uses same-origin `/api/fleet` for authorized coordinator operations
and `/api/infra` for the scoped projection. A tailnet connection does not replace
the coordinator bearer credential or project authorization. Tailscale Serve's
HTTPS hostname belongs to the tailnet domain; an organization-owned hostname
requires separately verified DNS, a certificate and a private TLS proxy.
A DNS CNAME alone does not supply the organization hostname's certificate.

The verified installed Hermes revision uses `CUSTOM_BASE_URL` to choose a custom
endpoint. The bridge binds both that variable and `OPENAI_BASE_URL` to the same
loopback gateway and supplies its key only in the child environment. The installed
Codex CLI requires `exec --ignore-user-config` in that order. These contracts
were discovered by real installation probes; mocks alone did not establish them.

The task client exposes `submit`, `list`, `status`, `logs` and `cancel`.
Use `python3 scripts/fleet_tasks.py --token-file /private/founder.token COMMAND`.
Submission allows 100 seconds for Hermes interpretation; all other operations
use 30 seconds. A rejected interpretation does not create a queued task.

## Parent/child task graph (step 2, source-tested only)

A task may be a child: `submit --parent <id> --role <role> --stage <plan|reference|review|dispatch|verify>` (API: `parent_id`, `logical_role`, `stage`). The coordinator remains the only state owner; there is no scheduler.

- One level deep, same project, at most 7 children per parent. A parent that is cancelled, cancel-requested, failed or interrupted takes no new children; a succeeded parent does.
- Roles are assigned by the caller (the Chief of Staff step), so children skip the Hermes bridge. Roots still go through interpretation.
- Cancelling a parent cancels queued children and requests cancellation of a running one.
- Parent detail carries `graph: {children, status}`. Status is derived on read: `verified` only when the parent and every child succeeded and a Sentinel child has a verified artifact; `failed` and `cancelled` take precedence; otherwise `incomplete` (or `none`).
- Execution is unchanged: one worker slot, FIFO claim, so children queue.

Evidence: `tests/test_fleet_task_graph.py` (14 tests) and the schema migration run against a copy of the live pilot database (columns added, 10 existing rows stay roots). Not yet deployed to the Coding 01 services, and the board does not render the graph yet.

## Retry and the write adapter (steps 2–3, source-tested; **disabled by default**)

**Retry.** `submit --parent P --role R --stage S --supersedes <failed child>`. Only a `failed` child can be retried (an `interrupted` one needs manual reconciliation because its outcome is uncertain); the retry must match parent, role, stage and access; at most 3 attempts per role. Superseded attempts stay visible (`superseded_by`, shown as "retried" on the board) but no longer count toward graph status or the 7-child limit.

**Write adapter.** A task may ask for `access: write`. It is refused unless **all** hold: the project sets `"write": true` in coordinator config; the principal lists the project in `"write_projects"`; the task is a graph child (`--parent`) with role `cto`; and the worker config enables it (`"write_roots": [<root>]` plus non-empty `"test_commands": {<root>: [{"argv": [...], "cwd": "rel", "timeout": 600}]}`; optional `"max_patch_bytes"`, default 1 MiB).

On a write task the worker runs Codex with `--sandbox workspace-write` and network off in a fresh detached worktree, then **computes the diff itself** and gates it:

- must be non-empty and valid UTF-8 text, at most `max_patch_bytes`;
- rejects denied paths (`.git`, `.github`, `_runtime`, `.env*`, `*.pem`, `*.key`, `id_rsa*`, `credentials*`, …), symlinks and submodules;
- rejects credential-like content (key prefixes, bearer tokens, private-key headers, the gateway key, the worker token);
- runs the allowlisted test commands (no shell); every one must exit 0 and none may change the tree.

On success the artifact carries `base`, `files`, the `patch` text with its sha256, and the test results. **Nothing is applied, committed or pushed**; a person reviews the diff and applies it (`git apply`). When tests fail or change the tree, the task fails and the patch is kept privately at `state/patches/<attempt>.patch`; gate failures keep no patch. Sentinel must still verify the graph before it counts as `verified`.

Evidence (source): `tests/test_fleet_write_access.py` (9), `tests/test_fleet_write_worker.py` (19, each gate mutation-checked), retry tests in `tests/test_fleet_task_graph.py`. Local: real Codex accepts the flags through the gateway; network and `git commit` blocked; writes outside the worktree blocked when the worktree is not under `/tmp`. Codex always treats `/tmp` and `$TMPDIR` as writable, so keep the worker state root outside them. Real Codex's `apply_patch` tool is unavailable through this gateway, so the preamble tells it to edit via shell. **Not deployed, not enabled, not run on the mini.**

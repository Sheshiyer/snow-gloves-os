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
and `/api/infra` for the scoped projection. The fleet proxy permits only task
list/detail/events GETs and bounded task-submit, cancel, and read-only fanout
POSTs; `/fanout` accepts only its existing empty object body. It keeps the
browser bearer and Origin headers for the coordinator to validate, and uses
bounded request/upstream timeouts. A tailnet connection does not replace the
coordinator bearer credential or project authorization. Tailscale Serve's HTTPS
hostname belongs to the tailnet domain; an organization-owned hostname requires
separately verified DNS, a certificate and a private TLS proxy.
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

**Manual Sentinel write review (source-tested, default-off).** After a CTO write child succeeds, its owner may submit a separate read-only Sentinel verification child with `--review-of <write-task-id>`, under the same parent and project. The project must explicitly set `"write_review_context": true`; the submitting principal must currently have both `read` and `submit` permissions. The coordinator freezes the source attempt and artifact SHA at submission, then checks the binding, current permissions, source state, parent state and project flag again at claim. Changed or unavailable evidence leaves the review queued with a generic hold reason. The claim contains only bounded, checksum-verified patch evidence and sanitized test status; task details, graph views and events do not expose patch bytes. The worker checks that the base commit is available locally and runs `git apply --check` before starting its read-only review runtime. It frames the exact patch as untrusted input and records the source binding in its result. It never applies the patch or grants write, merge or deployment authority. Automatic fanout remains read-only and cannot be widened by manually adding a review child.

The review envelope is capped at 1,000,000 bytes, the exact UTF-8 patch at 64 KiB, and delivered evidence at 96 KiB. Up to 100 sorted unique safe file paths and 16 successful test results are accepted. Test argv and raw tails are omitted. Unsupported rename/copy, binary, symlink/submodule, unsafe file-header and credential-like content is held rather than truncated or silently redacted. Read-only source inspection may examine the recorded base; it must not execute proposed code or tests. The native read-only sandbox is not a claim of repository-only filesystem read confinement.

Evidence: `tests/test_fleet_write_review.py`, plus 425 fleet/cockpit tests passing (one optional MCP SDK skip). An actual isolated native Codex candidate on Coding01 received the exact preserved 586-byte CTO patch at its recorded base, inspected source with four read commands, emitted no collaboration events and returned a checksum-bound Sentinel result. Direct inspection of its owned native session confirms the exact delivered patch and source binding. Its final referenced files exist; one comparison line citation needs correction from 233 to 236, so content is retained as a draft for human review. Final source additionally tightens artifact reads and credential rejection; the final fixture probe covers that stricter source. This feature is not deployed or enabled in the serving coordinator; production flags, services and human acceptance remain unchanged.

On a write task the worker runs Codex with `--sandbox workspace-write` and network off in a fresh detached worktree, then **computes the diff itself** and gates it:

- must be non-empty and valid UTF-8 text, at most `max_patch_bytes`;
- rejects denied paths (`.git`, `.github`, `_runtime`, `.env*`, `*.pem`, `*.key`, `id_rsa*`, `credentials*`, …), symlinks and submodules;
- rejects credential-like content (key prefixes, bearer tokens, private-key headers, the gateway key, the worker token);
- runs the allowlisted test commands (no shell); every one must exit 0 and none may change the tree.

On success the artifact carries `base`, `files`, the `patch` text with its sha256, and the test results. **Nothing is applied, committed or pushed**; a person reviews the diff and applies it (`git apply`). When tests fail or change the tree, the task fails and the patch is kept privately at `state/patches/<attempt>.patch`; gate failures keep no patch. Sentinel must still verify the graph before it counts as `verified`.

Evidence (source): `tests/test_fleet_write_access.py` (9), `tests/test_fleet_write_worker.py` (19, each gate mutation-checked), retry tests in `tests/test_fleet_task_graph.py`. Local: real Codex accepts the flags through the gateway; network and `git commit` blocked; writes outside the worktree blocked when the worktree is not under `/tmp`. Codex always treats `/tmp` and `$TMPDIR` as writable, so keep the worker state root outside them. Real Codex's `apply_patch` tool is unavailable through this gateway, so the preamble tells it to edit via shell. **Not deployed, not enabled, not run on the mini.**

### Verification confinement (ISC-383) — fix, source/local only

Finding (recorded in the platform ISA by an independent audit): the write adapter ran its allowlisted test command directly. Because the agent can edit a test or script that command executes, an argv allowlist and a worktree `cwd` do not confine the code. The audit probe wrote outside the worktree and the task was still accepted.

Fix: every verification command now runs under macOS Seatbelt (`sandbox-exec`) with a generated profile: writes only in the worktree and a private scratch dir (also its `HOME` and `TMPDIR`); no reads under `$HOME` (override `verify_deny_read`); no network except loopback; no signals outside its own sandbox. It fails closed when `sandbox-exec` is missing or cannot apply the profile (`sandbox_exec_path` to override the path). Interpreter libraries living under `$HOME` must be listed read-only in `verify_python_paths` (also added to `PYTHONPATH`), e.g. the user site-packages that holds pytest.

Allowlist guidance: do **not** put `tests/test_fleet_write_worker.py` in `test_commands`; its tests start their own sandboxes and macOS cannot nest them. Any test file that does not itself call `sandbox-exec` works: `test_fleet_coordinator.py`, `test_fleet_task_graph.py`, `test_fleet_write_access.py`, `test_fleet_execution.py` and `test_fleet_scoped_principals.py` pass 69/69 inside the sandbox in about 6 s. Pytest living in the user site-packages needs `verify_python_paths`.

Limits: macOS only. A script that swallows the denied write and exits 0 is not detected as a violation, only prevented from changing anything. Reads outside `$HOME` (system files) remain possible. Write stays disabled on the mini until this is deployed and re-probed there.

## Connecting other Hermes clients (fleet MCP over SSH)

`scripts/fleet_mcp.py` is a stdio MCP server that wraps the coordinator's six
tools: `fleet_list`, `fleet_status`, `fleet_logs`, `fleet_cancel`,
`fleet_fanout`, and `fleet_submit` (with `parent_id`, `logical_role`, `stage`,
`supersedes`, `access`). `fleet_fanout(task_id)` sends only `{}` to the
existing validated task route; it has no role, scope, option, credential-export
or scheduler override. It is a thin loopback client; authentication, project
scope, fanout admission, the task graph and the write gates all stay in the
coordinator, and the operator token is read on Coding 01 and never leaves it.

On Coding 01 a wrapper (not in Git, like `snowgloves-fleet`) runs it with the Hermes Python that has `mcp`:

```sh
~/.local/bin/snowgloves-fleet-mcp      # exec <hermes venv python> scripts/fleet_mcp.py --token-file <founder.token>
```

From another Hermes install on the tailnet that has the `coding-01-tailnet` SSH alias:

```sh
hermes mcp add snowgloves-fleet --command ssh --args coding-01-tailnet /Users/axio/.local/bin/snowgloves-fleet-mcp
hermes mcp test snowgloves-fleet
```

Limits: whoever can SSH to the account gets the founder's coordinator authority (per-person principals are checklist row F04). Write stays off at the coordinator, so `access=write` returns 403. The SSH hop itself was not exercised from the authoring Mac; the wrapper was exercised over stdio with a real MCP client against the live coordinator.

## Scoped principals (read-only observers)

A coordinator principal may carry `"permissions"` (any of `read`, `submit`, `cancel`; absent means all three, so existing principals are unchanged) and `"view_owners"` (names of other principals whose tasks it may read). Viewing never grants mutation: cancelling, submitting, attaching children and fanout stay with the task owner. Fanout additionally requires current `submit` permission and the default-off project/principal fanout admission. Config load rejects unknown permissions and unknown owners.

Example observer: `{"token": "...", "projects": ["snowgloves"], "permissions": ["read"], "view_owners": ["founder"]}`. It can list, read detail and events (including a parent's graph); submit, cancel and write return 403. Source: `tests/test_fleet_scoped_principals.py` (13 tests, the owner-only rule mutation-checked, plus an HTTP round trip).

## Transient provider errors (bounded safe retry)

Live write and review attempts intermittently failed with `429 Too Many Requests` from the gateway: `noesis-execute` is a priority combo whose first member is a free-tier model that keeps going into cooldown (OmniRoute app log, `command-code/poolside/laguna-s-2.1-free`). Host routing is not changed from this repo.

The worker now retries a failed Codex run only when the failure is a transient provider error (429, "Too Many Requests", dropped stream) **and the run provably did nothing**: no command, file change, tool or web call started. Up to `transient_retries` (default 2) fresh runs, waiting `transient_backoff` seconds (default 20) times the attempt number, with heartbeats, cancellation, shutdown and the overall `job_timeout` still honoured during the wait. Each run keeps its own log (`<attempt>.retryN.jsonl`). Anything that ran, any other failure, and any uncertain outcome are never replayed. Tests: `tests/test_fleet_transient_retry.py` (10, both safety conditions mutation-checked).

## Preserving worker worktrees during cleanup

`scripts/fleet_worker_gc.py` defaults to a dry run. A `remote_artifacts` worker keeps no local result file, so when the coordinator accepts its success report it writes `<state_root>/acknowledged/<task>-<attempt>.json`, which cleanup treats as the result artifact; failed, cancelled, interrupted and rejected attempts get no marker and stay preserved. An old result artifact does not prove that all work in its checkout has been preserved. Cleanup keeps tracked edits, staged edits, untracked and ignored files, unknown Git state and detached commits that no branch or tag retains. Preserve that work in a reviewed recovery archive before considering removal; a retained branch only saves committed history.

Any `recovery-required.json` file holds all cleanup, matching the worker's dispatch hold. Malformed or unreadable active/pending records also hold all cleanup. A valid active/pending record protects its specific attempt. `--include-failed` relaxes only the result-artifact requirement, never these preservation gates.

Removal rechecks assignment holds and checkout state, then uses normal Git worktree removal so dirty or locked checkouts are refused. A refusal stops the apply operation for review; it does not retry with `--force`. Source tests use real disposable Git repositories to cover these boundaries. This change does not archive or remove any live worktree.

## One worker job also means no internal subagents

An isolated real Coding01 run exposed a capacity gap: one admitted Codex invocation used its native collaboration tools to create additional agent threads. The candidate worker now disables both `multi_agent` and `multi_agent_v2` per invocation, for read and write jobs. The installed CLI recognizes both switches; they do not change the user's native configuration. Role assignments remain explicit coordinator tasks.

Automatic transient retry requires a complete structured attempt trace with thread start, turn start and a transient failed turn. Only reasoning, message and error items count as evidence without effects. Collaboration calls, any other tool item, future unknown item types, malformed records, missing boundaries and conflicting failures prevent replay. Unknown outcomes retain their original task and attempt for reconciliation.

The first isolated real-flow probe interpreted and planned through pinned Hermes, but its root hit the time limit after collaboration activity; its queued children did not run. Preserve that interrupted attempt. It does not prove predecessor delivery, semantic validation or production acceptance.


Actual corrected candidate flow on Coding01 completed root → Librarian → Sentinel with the pinned Hermes bridge and three sequential Codex jobs, all with zero collaboration events. Exact predecessor output was verified in the owned CLI session prompts, rather than inferred from artifact references. Sentinel corrected five root citation offsets against the real checkout. This isolated run leaves production admission and human semantic acceptance pending; the serving board remains unchanged. The first interrupted candidate and all recovery evidence are preserved without replay.

## Running each tenant's tasks as its own account (optional, off by default)

The worker and every other service run as the operator account, which owns all private instance data: the ops checkout, every tenant workspace, backups, configs and the gateway key. The read-only Codex sandbox does not confine reads, so a tenant task run as that account could read any of it, whatever the private clone and history checks do. Folder permissions cannot hide files from their owner, so isolating tenant tasks needs other accounts.

Each tenant gets its own account. A shared account would keep tenants out of the operator's data but not away from each other: one run could leave data for another tenant's run through files, or through same-account state that leaves no files, such as named POSIX semaphores, which Codex's sandbox allows. With one account per tenant, such state is visible by default only to the same tenant's later runs.

**Known limit: deliberate hand-offs through named semaphores.** Separate accounts stop one tenant's task from reading another tenant's data. They do not stop two compromised tasks from passing data on purpose. Codex's sandbox allows named POSIX semaphores. A task can create one that other accounts may open (mode 0666), and that semaphore outlives the run. macOS gives semaphores no file and offers no way to list them, so the worker cannot scrub them. So a compromised task of tenant A could store A's data in semaphore values for a later compromised task of tenant B to read. This needs a compromised task on both sides; it does not let any task read another tenant's files. The worker cannot add a rule to Codex's sandbox, and macOS refuses a second sandbox around Codex's own (`sandbox_apply: Operation not permitted`). So closing this means one of two things: replace Codex's sandbox with a worker-owned profile that also denies `ipc-posix-sem`, or give each tenant its own host or VM.

With `task_users` (a map from tenant slug to account) and `task_root` set in the worker config, each tenant-isolated task (`tenant_isolated` in its claim) runs this way:

- The worker looks up the tenant's account. A tenant with no entry is refused; it never runs as another tenant's account or as the operator. Every tenant must map to a different account (compared by UID, so two names for one UID are refused), and the old single `task_user` setting is rejected.
- The worker creates `<task_root>/<task>-<attempt>/` (mode 700) as the operator and makes the private clone in `repo/` there. The clone is outside the operator's home.
- ACL entries give that tenant's account read access to `repo/`, and full access to a fresh `home/` that serves as `HOME`, `CODEX_HOME` and `TMPDIR`. The account gets nothing else.
- Codex runs as `sudo -n -u <account> --preserve-env=<names> -- <codex …>`. The gateway key goes through the environment only, never the command line.
- Stopping a run signals the group as before, then runs `pkill -KILL -U <account>` as that account, because sudo cannot relay SIGKILL. Before and after each run, and for every account at worker start, the worker checks with `pgrep -U <account>` (as itself) that the account runs nothing, ending what it still runs and re-checking for a few seconds. If that can't be confirmed, the run is refused or dispatch is held.
- Before and after each run, and for every account at worker start (a crashed run never got its post-run scrub), the worker deletes everything the account owns in the shared writable folders (`task_scrub_roots`, by default `/private/tmp`, `/private/var/tmp` and `/Users/Shared`) and in the account's per-user temp and cache folder (`getconf DARWIN_USER_DIR`), then checks nothing is left. It looks inside every folder the account can enter. A folder the account can enter but not list could hide its files, so finding one fails closed. Files and folders there that another account owns but the task account may write (group- or other-writable, or with an ACL) cannot be deleted. The worker fingerprints them before the run: files by size and times, folders by mode, owner, extended attributes and ACL, plus their entries (names and inodes) when the folder has no sticky bit or carries an ACL, since then the account could delete or rename another account's entry. The scrub roots themselves are fingerprinted the same way. The account's own per-user folder is fingerprinted without its entries (the scrub empties them) but with its extended attributes and ACL; if the worker cannot read that folder, the scrub fails closed (macOS creates it readable, mode 755). It holds dispatch if any changed by the end, or by the next start after a crash. Any other failing step fails closed too. The scrub covers the scrub roots only: symlinks inside them are treated as entries, not followed, because a link only names a place the account could already reach by its own path, and following every link (a dev host's /tmp holds many, into node_modules and tool folders) would pull arbitrary trees into the scan. To cover another writable folder, add it to `task_scrub_roots`. Tenant tasks also run under Codex's read-only sandbox, which refuses writes outside the task's own folders.
- After the terminal report is written to disk, a succeeded run's workdir is deleted (`home/` as the account, the rest as the operator) and checked gone. Any other run, or one whose deletion fails, is moved to `<state_root>/retained-task-workdirs/` for reconciliation. Workdirs a crash leaves in `task_root` are moved there at the next start. If a workdir can be neither deleted nor moved, dispatch is held (`recovery-required.json`).
- `task_root` and each new workdir must carry no ACL entries of their own; mode 711 says nothing about ACLs.
- Write tasks are refused on this path; tenant projects are read-only.

Without these settings the worker behaves as before.

**One-time setup (needs an administrator):**

1. For each tenant the worker serves, create a standard account (for example `sg-t-<tenant>`; macOS short names are at most 32 characters). Each needs:
   - no admin rights and no login shell;
   - no home folder (`/var/empty`);
   - no SSH or Screen Sharing access;
   - its own primary group rather than `staff`, so group-readable files in other homes stay out of reach.
2. Make the operator's home owner-only: `chmod 700 /Users/<operator>`. Without this, every member of `staff` can read the operator's 755 folders, the ops checkout included.
3. Create `task_root` outside that home and outside every `task_scrub_roots` tree (for example `/Users/snowgloves-task-runs`, not a child of `/Users/Shared`), owned by the operator with mode 711 and no ACL entries (`ls -led` shows none). Other accounts can pass through it but not list it. A searchable but unlistable task root inside a scrub tree causes the scrub to fail closed.
4. Add `/etc/sudoers.d/snowgloves-task` (edit with `visudo -f`) so the operator can run only these commands as the tenant accounts, without a password and keeping the listed environment:

   ```
   Runas_Alias SG_TENANTS = sg-t-tenant-a, sg-t-tenant-b
   <operator> ALL=(SG_TENANTS) NOPASSWD:SETENV: /opt/homebrew/bin/codex, /usr/bin/pkill, /bin/rm, /usr/bin/find, /usr/bin/getconf
   ```

   Each runs with that tenant account's rights only. Add a tenant's account to the alias when you admit the tenant.
5. In the worker config, set `task_users` (for example `{"tenant-a": "sg-t-tenant-a", "tenant-b": "sg-t-tenant-b"}`), `task_root`, and if needed `sudo_path`. Then restart the worker.

**Check before relying on it:**

- For each account, run `sudo -u <account> cat /Users/<operator>/Projects/<ops checkout>/fleet.yaml`, plus the same for another tenant's workspace and the gateway key. Each must be denied.
- Run one real task per tenant and confirm it succeeds and its result imports.

**Rollback:** first fence private tenant submissions and remove those projects from the worker's eligible grants; keep that fence in place throughout rollback. Removing `task_users` and `task_root` restores operator-account execution, so a healthy worker after rollback is not tenant privacy acceptance. Restore the reviewed worker/configuration backup, restart only in the approved maintenance window, and verify the fenced grants before allowing platform-only work. Remove the dedicated sudoers entry only after task accounts are idle. Restore the home folder's earlier mode only if the reviewed rollback explicitly requires it and no private tenant work can run. Re-admit private tenant projects only after the dedicated-account denial and real-task checks pass again.

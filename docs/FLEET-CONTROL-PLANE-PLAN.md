# Fleet orchestration and visualization — design candidate

Date: 2026-09-30. Target: 40–50 concurrent sessions across 4–5 Macs.
Status: architecture and load-test target; no fleet implementation or capacity
claim. Adds the missing operating layer to specs/005-node-bootstrap.

Owner-used upstream candidates: [Orca/OpenOrca fit review](ORCA-OPENORCA-FIT-REVIEW.md).
Evaluate reusable workspace/dashboard surfaces before implementing those from
scratch; retain one governed control-plane authority.

## Network-first architecture

One logical control plane owns memberships, scheduling, commands, run/session
metadata, approvals, and event history. Each Mac runs an enrolled outbound node
agent that launches local runtime adapters and reports results. The browser
dashboard and CLI use the same authenticated API. Loopback endpoints remain
internal adapters; no remote client receives another host's localhost URL.

Preferred deployment candidate: Cloudflare Worker API/identity edge, per-org
Durable Object coordination and replayable event stream, optional Queue for
asynchronous notifications, and R2 for scoped artifact objects. Coordination
authority resides in the control plane, not a second independent scheduler on
the primary mini. This refines the earlier primary-mini coordinator proposal:
the mini hosts execution and OmniRoute, while authoritative fleet leases move
to the control plane. A self-hosted pilot may implement the same protocol, but
production chooses one writer backend; do not dual-write competing authorities.

Cloudflare is not the CLI compute host. Minis run processes, browsers, builds,
and tool calls. OmniRoute stays a private inference service, reachable through
authenticated transport and invocation policies. Dashboard subscriptions are
filtered by organization and brand, not broadcast to every connected user.

## Protocol and streaming

Nodes register capabilities and connect outbound over TLS WebSockets, with
HTTPS polling fallback. Enrollment credentials are short-lived/scoped; peer
identity is distinct from org permissions. Heartbeats advertise free/used memory,
CPU pressure, disk space, active slots, tool versions, and available adapters.
Version negotiation rejects incompatible nodes before assignment.

Commands have stable IDs, scope, expiry, expected state/version, policy version,
and fencing epoch. Acknowledged intent, started execution, finished execution,
and committed result are distinct. Use application acknowledgments and durable
state; an open socket is not a command receipt.

Events include org/brand/node/session/run/attempt references, producer sequence,
event ID, type, timestamp, trace ID, and schema version. Deduplicate on ingestion;
assign authoritative stream cursors and per-run ordering. Persist critical state
events before acknowledgment. Reconnect resumes from a cursor; retention gaps
return a fresh snapshot plus new cursor. Bound output buffers and upload chunks
with checksums. Slow dashboard clients cannot block process execution; explicitly
mark truncated output. Store terminal text separately from metadata and apply
RBAC/redaction/retention. Secret-free summaries are the default fleet feed.

Queue delivery is at least once and not ordered; it cannot alone establish job
ownership or exactly-once external effects. Lease transactions and action
idempotency enforce admission. Unknown provider outcomes stay in-doubt until
reconciled; expired leases do not authorize blind campaign resend.

## Session, run, and workspace model

A session is durable conversation/work context. A run is a scheduled execution
attempt within it. A process is node-local and disposable. Runtime-native session
handles remain local; central opaque references map them without publishing native
identifiers. Opening 50 sessions is distinct from 50 executing processes and
50 simultaneous provider requests.

Same-node attach may reconnect to an existing runtime process. Cross-node handoff
is checkpoint-and-resume where supported, or a new runtime session seeded from
approved context. Do not promise transparent live memory/process migration or
cross-runtime native conversation migration. Capability badges disclose support.

Code runs have independent Git worktrees tied to source revision. Handoffs carry
reviewed commits or patch/artifact digests and portable workspace refs. A target
verifies inputs and local dirty state before execution; never sync an entire live
checkout or database through iCloud/shared filesystems. Pause/drain source runs,
revoke old leases, and fence writes before transferring ownership. Parallel tasks
can branch; ordered dependencies advance only on accepted predecessor results.

## Scheduler and capacity

Admission combines per-node memory/CPU/disk reservation, per-org fair-share limits,
runtime support, provider concurrency/rate/token quotas, campaign budgets, and
exclusive workspace/action locks. Reserve resources atomically before assignment.
Keep queue state visible and cancellable. Support priority aging and drain mode.
Node loss permits safe recomputation, but cannot make an uncertain send safe.

Initial target: 50 durable sessions; mixed idle, awaiting approval, streaming,
and executing states. Four to five Macs means an average of 10–12.5 sessions per
Mac, not a guaranteed safe active-process count. RAM is unknown. Benchmark CLI,
browser, build, and media profiles separately. Measured peak memory plus headroom
determines active slots. API/subscription quotas can constrain throughput before
hardware does; do not assume hardware multiplies provider entitlement.

## Operator visualization

The owner's selected visual direction is the playable 3D pixel-art
[Session World](SESSION-WORLD-DESIGN.md), paired with an equivalent list view.
Both consume the same scoped events and authorized command API.

- Fleet map: machines, role, heartbeat age, resource pressure, slots, versions.
- Session board: org/brand, runtime, node, current step, waiting reason, last event.
- Workflow graph: dependencies, parallel branches, approval gates, accepted outputs.
- Run detail: timeline, scoped terminal stream, artifacts, attempts, cost, policy.
- Handoff view: source/target, checkpoint, lease/fence state, dirty workspace check.
- Attention inbox: login needs, approvals, failures, stale nodes, unknown outcomes.
- Budget view: provider quota versus actual compute slots, spend by brand/campaign.

Submit, attach, pause, resume, cancel, drain, transfer, approve, and retry are
audited commands with server authorization. Viewing a terminal is not permission
to type into it. Terminal control needs an exclusive scoped control lease and
explicit supported transport. Never expose arbitrary shell execution through a
viewer token. RBAC applies to historical replay, artifacts, exports, and search.

## Pilot and evidence gates

1. One physical Mac, separate control-plane and node processes, authenticated
   network API; prohibit implicit shared memory/direct database access.
2. Two simulated nodes on that Mac: job leases, duplicate events, reconnect replay,
   slow subscribers, partitions, stale policy, drain, cancellation, handoff tests.
3. Two real Macs: private connectivity, worker kill/reboot, artifact transfer,
   lease fencing, supported runtime continuation, independent worktree proof.
4. Four/five Macs: 50-session mixed-state soak, plus an explicit all-active test
   only at verified hardware/provider limits. Record workload and quotas.

Proposed thresholds for review: 2-hour 50-session soak; p95 state-to-dashboard
latency under 2 seconds on a healthy link; metadata replay completes within 30
seconds after reconnect; offline indication within 30 seconds; zero lost committed
state events, unauthorized cross-brand streams, duplicate accepted results, or
duplicate external actions. Provider failures do not turn into fleet success.
Compare one-node and multi-node behavior using the same conformance suite.

## References

- https://developers.cloudflare.com/durable-objects/best-practices/websockets/
- https://developers.cloudflare.com/queues/reference/delivery-guarantees/
- https://developers.cloudflare.com/queues/reference/how-queues-works/

## Next planning tasks

Extend the node spec with control-plane API/event schemas, scheduler state machine,
runtime attach capabilities, dashboard UX contract, scoped subscription tests,
retention rules, load fixtures, and lease/fencing acceptance. Add the node agent
and control-plane endpoint/version to bootstrap and doctor. Implementation and
live capacity verification remain pending.

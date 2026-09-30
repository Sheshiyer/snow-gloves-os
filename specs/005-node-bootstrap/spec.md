# Node bootstrap, diagnostics, handoff, and organization authorization

Status: draft for review, 2026-09-30. Planning only; no activation authority.
Extends docs/MAC-MINI-NODE-ONBOARDING-PLAN.md. Existing install and doctor
remain available until replacement acceptance. This feature owns node lifecycle,
not OmniRoute configuration authority or provider sessions.

## Goal

A fresh Apple Silicon mini can progress from inspected hardware to a verified
Snow Gloves role through a resumable CLI and Claude start prompt. A second
operator/runtime can resume from a bounded checkpoint without gaining authority.
Every sensitive operation enforces verified organization and brand permissions.

## Bootstrap state machine

```text
uninspected → inspected → planned → applying → configured → verifying → ready
                                  ↘ waiting-human / failed → resume
                                  ↘ rolling-back → rolled-back / manual-recovery
```

Plan captures manifest digest, node identity, selected role, supported versions,
dependency DAG, target files, privileges, costs, and rollback actions. Apply
requires the same reviewed plan digest and fresh preconditions. A node-local
lock prevents concurrent apply. Changed plans or config produce drift, not
silent continuation. Individual stage results are atomic and durable.

Stage order: prerequisite Claude entry → hardware/identity → developer tools
→ runtime/secrets/network → supervised services → brand capabilities
→ operations/recovery → operator apps/CLIs → acceptance. Independent downloads
may parallelize; configuration, enrollment, and service promotion are serialized.
Failed prerequisites block dependents. Resume re-probes completed stages rather
than trusting old checkboxes. Rollback touches only installer-owned changes;
external actions with no safe inverse are held or require manual recovery.

Proposed commands: `node inspect`, `plan`, `apply`, `resume`, `status`, `doctor`,
`debug collect`, `handoff export`, `handoff verify`, and `rollback`, beneath the
future `snowgloves` CLI. Structured JSON and readable output share one result
model. No invented working commands in the README before implementation.

## Doctor contract

Default doctor is read-only and performs no secret retrieval, inference,
generation, enrichment, or delivery. Network probes are opt-in and bounded.
Repair prints a plan; apply requires its digest and appropriate authorization.

| Area | Probe and what it proves |
|---|---|
| Host | Architecture, RAM, free disk, clock, power configuration, reachable node identity |
| Toolchain | Resolved binary, supported version, fresh-shell PATH, environment/lockfile consistency |
| Runtime | Installed package digest, rendered config, version-negotiated health response |
| Services | launchd ownership, executable identity, PID/start time, authenticated service identity; port alone fails |
| Network | DNS/TLS, private connectivity, Access identity, application auth; separate from provider authentication |
| Vault | Enrolled device and permitted metadata; synthetic retrieval only under explicit test mode |
| Providers | Config reference and supported auth check; chargeable behavior requires a budgeted separate canary |
| Organization | Verified subject, active membership, role scope, policy version, revocation freshness |
| Jobs | Queue age, leases, worker availability, fencing epoch, resource limits, in-doubt actions |
| Recovery | Backup age/checksum, restore evidence, unattended restart and disk-unlock evidence |
| Operator tools | App/CLI version, independent auth state, adapter compatibility, synthetic-task evidence |

Findings: pass, fail, warn, unknown, skipped. Include stable check ID, target
scope, observed time, expiry, expected/actual metadata, reason, evidence digest,
and remediation. Skipped mandatory checks keep readiness held. Use exit 0 for
profile-ready, 1 for failed mandatory checks, 2 for held/unknown requirements,
3 for invalid invocation; command errors never masquerade as findings.

## Organization and brand RBAC

Canonical hierarchy: portfolio → legal entity/organization → brand → project
→ campaign. Legal/company ownership must be source-backed and founder-reviewed.
External identity is verified issuer + subject, never email/display-name alone.
Membership and policy are server-owned. Bootstrap establishes the first owner
through a one-time authenticated enrollment, not a locally editable role file.

| Role | Default scope and capabilities |
|---|---|
| Portfolio owner | Explicitly assigned portfolio governance; reviewed grants and budgets |
| Org admin | Assigned org membership/config; no automatic secret retrieval or campaign sends |
| Brand operator | Assigned brand research/drafting, permitted connector use, proposal creation |
| Campaign approver | Approves bound audience/content/channel/budget; cannot approve own high-risk proposal |
| Executor service | Executes exact approved action within job and connector scope; cannot grant or approve |
| Auditor | Redacted evidence and configuration status; no secret values or contact exports by default |
| Node maintainer | Assigned node install/repair; no implied organization data access |

Require explicit grants for secret.read, secret.write, provider.invoke,
connector.configure, campaign.propose, campaign.approve, campaign.execute,
membership.manage, and node.maintain. Deny by default. Evaluate verified subject,
active membership, scope, device state, policy version, capability, approval,
and remaining budget at every enforcement boundary. Client files cannot grant
roles. A trusted mini or shared Apple account is not an organization principal.

Approval binds approver identity, organization/brand, action digest, immutable
recipient snapshot, content digest, connector identity, budget, expiry, policy
version, and idempotency key. Enforce before queueing and immediately before
external dispatch. Revoke membership/device/approval without waiting for long
token expiry; define maximum revocation propagation and fail closed when stale.
Break-glass recovery is time-limited, separately audited, and cannot silently
enable campaign delivery. Tokens are audience-bound and narrowly scoped.

## Debugging and handoff

Debug tools: structured logs, `launchctl`, `lsof`, process inspection, DNS/TLS
probes, `jq`, `rg`, package/version inspection, queue and lease inspector,
policy explain, config diff, artifact checksum, and restore verifier. Read-only
tools first; debug bundles exclude environment dumps, tokens, prompt bodies,
native sessions, contact lists, and arbitrary file captures.

Runtime checkpoint schema `snowgloves.node-handoff.v1`: node/role refs, run ID,
manifest/plan/source/config digests, completed stage receipts, pending stages,
failures, waiting-human steps, policy version, expiry, rollback checkpoint ref,
last verification, owner-scope refs, and next command. Paths are portable refs.
No credentials, session IDs, access tokens, or raw API bodies. Sign with the
enrolled device identity. Import verifies signature, schema, scope, expiry,
source/plan match, and current state; it never imports approvals or role grants.
Checkpoint tampering or stale state blocks resume. Export/import are auditable.

## Acceptance

- Fresh mini reaches profile-ready with one selected coordinator role.
- Repeated apply performs no duplicate install/config/enrollment effects.
- Interrupted apply resumes without losing stage evidence.
- Drift, concurrent apply, failed prerequisite, and partial rollback fail safely.
- Doctor rejects a wrong process on the expected port.
- Doctor reports stale/unknown mandatory evidence as held.
- Default doctor and debug make zero paid calls and expose zero synthetic secrets.
- Readiness distinguishes installed, authenticated, configured, running, and proven.
- Org A principal cannot access Org B; brand scope cannot widen to portfolio.
- Node maintainer cannot retrieve brand secrets; executor cannot approve itself.
- Revoked membership/device and expired or tampered approvals block dispatch.
- Changed recipient/content/budget invalidates prior approval.
- Signed handoff resumes in another runtime; stale/tampered handoff is rejected.
- Handoff cannot confer roles or replay an already consumed external action.
- Backup restore and reboot/disconnect continuity are demonstrated on a pilot.
- All operator CLIs have verified identity/version and bounded synthetic receipts.

Detailed thresholds, cryptographic format, storage engine, identity provider,
supported package versions, Grok distribution, and actual hardware inventory
remain implementation-plan decisions. No live RBAC is verified by this spec.

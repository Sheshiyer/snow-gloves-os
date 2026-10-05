# Orca / OpenOrca fit review

Date: 2026-09-30. Bounded upstream README/docs and entry-route inspection;
unpinned main snapshots, no installation, runtime test, or full security audit.

## Proposed disposition

Evaluate stablyai/orca as an operator workspace adapter. Use OpenOrca as a
candidate/reference for the fleet visualization and intervention experience.
Snow Gloves retains verified organization/brand authority, scheduling, job
leases, audit, and campaign permissions. Neither upstream is certified for this
fleet's 50-session target by this review.

## Orca evidence

The README documents parallel isolated worktrees, terminal panes, multiple agent
CLIs, a CLI automation interface, and SSH remote workspaces. The SSH docs describe
remote agents with local editing/review. This is relevant to Mac-based execution.
Its cloud README describes outbound-WebSocket mobile/desktop relay infrastructure
using GCP services/PostgreSQL and identifies private API/auth infrastructure not
included in the public relay tree. Cloudflare deployment is not a drop-in claim.

Before selection, pin a release/source revision and verify macOS remote support,
CLI event/command coverage, session restoration, scoped terminal controls,
OmniRoute configuration, deployment dependencies, and actual load behavior.
Review subscription/session handling against the owner's supported auth model.

The invoked Temperance skill currently prescribes Superset/Claude for Hands.
Orca remains an evaluated alternate cockpit until a reviewed execution-adapter
decision authorizes it; do not silently replace the existing Hands contract.

## OpenOrca evidence and limits

The README describes a fleet command center with machine-linked agents,
timelines, interventions, and collaboration views using a web application stack.
In inspected server/routes.ts, a shared WebSocket client set receives broadcast
updates without organization filtering in that handler. Inspected route and
server entry code do not establish verified subject/membership authorization.
This is a bounded source finding, not a claim about an owner's external proxy.
server/index.ts logs serialized API responses; minimize/redact this before
operational contact or conversation data is connected. These source paths need
reviewed replacements before multi-org use.

Do not equate an intervention UI with enforced campaign approval. Integrate it
with exact-action RBAC, scoped replay, expiry/revocation, lease ownership, and
provider receipt reconciliation. Determine whether to adapt components or keep
only the interaction patterns after pinned source and license review.

## Integration spike and decision gate

1. Pin upstream revisions/licenses and inventory extension surfaces.
2. Run one-Mac synthetic sessions using an explicit adapter, outside live brands.
3. Normalize upstream session/process events into fleet session/run/attempt IDs.
4. Prove viewer/control permissions, reconnect replay, and zero cross-brand leaks.
5. Test two-node worktrees/checkpoint transfer; disclose runtime-native limits.
6. Benchmark 50 mixed-state sessions and separate all-active resource limits.
7. Select cockpit and dashboard independently; retain one authority/writer.

## Primary sources

- https://github.com/stablyai/orca
- https://www.onorca.dev/docs/ssh
- https://github.com/stablyai/orca/blob/main/cloud/README.md
- https://github.com/ianpilon/OpenOrca
- https://github.com/ianpilon/OpenOrca/blob/main/server/routes.ts
- https://github.com/ianpilon/OpenOrca/blob/main/server/index.ts

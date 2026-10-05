# Implementation plan — draft

## Evidence baseline

scripts/install.sh requires existing tools, installs dependencies, and prints
next steps. scripts/doctor.sh mutates an audit probe and can label port 3100 as
Paperclip without service identity. connectors/g-stack/auth.py is explicitly a
stub; its active record and synthetic vault ref do not prove authentication.
scripts/approvals.py changes local ticket state without verified approver RBAC.
Existing tenant enablement is admission policy, not server identity enforcement.

## Work packages and dependencies

Persistent-agent lifecycle and initial handoff bindings:
[Agents infrastructure handoff](../../docs/AGENTS-INFRA-HANDOFF-PLAN.md).
Agent, environment, session, vault attachment, workflow, and artifact identities
are separate resources admitted before first execution.

Fleet orchestration and dashboard extension:
[control-plane design](../../docs/FLEET-CONTROL-PLANE-PLAN.md).
Its network-first protocol and 50-session load gates apply to the pilot.
The cloud control-plane candidate supersedes the primary-mini authoritative
scheduler proposal; final backend selection remains open and there is one writer.

1. Contract/schema: define release manifest, node plan, stage receipt, doctor
   finding, handoff, membership, policy, and approval schemas. Stable IDs and
   migrations; closed inputs; separate portable metadata from machine-local refs.
2. CLI foundation: project-isolated Python/uv packaging candidate, structured
   stdout/stderr, standard exit codes, cancellation, locking, atomic checkpoints.
   Decide packaging after fresh-machine entry and existing CLI integration review.
3. Inspect/plan engine: read-only inventory, DAG, package source/version checks,
   preconditions, permissions, disk/cost bounds; no installation side effects.
4. Apply/resume/rollback: owned-file journal and validated adapters; mock package
   manager tests before disposable/fresh-machine pilot. Never global pip upgrades.
5. Identity/RBAC/vault: select verified issuer; server-side memberships and scope
   checks; device enrollment; action approvals; revocation and audit storage.
   Depends on schemas; live connectors remain held until negative tests pass.
6. Runtime/services: pinned Temperance/OmniRoute inventory, private transport,
   launchd, secret delivery, queue/leases; preserve Hands versus Hermes planes.
   Superset/Claude via OmniRoute is the skill's Hands execution lane. Codex app
   remains cockpit; include Superset tooling in the selected coordinator profile.
7. Doctor/debug: typed probes and policy explain, redacted bundles, bounded live
   read checks, separate budgeted canaries. Depends on runtime/identity contracts.
8. Handoff: sign/export/verify/resume, current-state reconciliation, portable refs,
   retention; no authority imported from a file. Depends on journal and identity.
9. Operator/capability packs: Codex app/CLI, Claude, verified Grok, approved MCPs,
   lead/media adapters, scopes and budgets; independent install/auth checks.
10. Pilot: one node/brand and synthetic workload, then two-node lease failure,
    reboot, revoke, restore, drift, and in-doubt reconciliation acceptance.

## Verification and handoff gates

Run focused schema/state-machine/policy tests, then existing `make test` and
catalog checks for affected integration. OS/service tests require a disposable
Mac pilot; mocks do not certify reboot or credential access. Synthetic fixtures
cover secrets and campaigns; live paid canaries need scoped budget authorization.
Every package supplies source revision, changed files, commands/results, known
limits, rollback, and next step. Local source, installed, live, and human approval
states remain separate. No merge, deployment, or installation is implied.

## Open decisions

RAM/location inventory; canonical org/brand sources; identity issuer; authoritative
policy/job storage; trusted signing/encryption format; unattended key availability;
supported OmniRoute/provider authentication; exact Grok/GetLeads products; retention
and revocation thresholds; account-specific Cloudflare resources and cost limits.

# Persistent agents: environments, sessions, vaults, and handoff

Status: planning candidate, 2026-09-30. Official Agents API documentation checked;
no agent, environment, executor, session, or vault provisioned. Availability,
permissions, selected SDK versions, and macOS behavior require a pilot.

## Resource model from initial planning

Every admitted workflow binds an immutable agent-definition version, org/brand
scope, workflow/run identity, execution-adapter type, environment profile, skill
and MCP catalog digests, required credential references, budget, policy version,
source revision, and output acceptance contract before its first turn.

| Resource | Responsibility |
|---|---|
| Agent definition | Reusable role/instructions/tools/model policy; not a permission grant |
| Environment profile | Workspace, packages, node/runtime capability, network allowlist, isolation |
| Session | Durable provider conversation/work; mapped privately to a canonical fleet session |
| Workflow state | Trigger, dependencies, approvals, leases, retries and accepted results |
| OpenAI vault attachment | Selected MCP/environment credentials for managed execution |
| Local secrets vault | Device-scoped credential sync for local runtimes |
| Artifact/knowledge store | Approved facts, source files, checkpoints and results; not a credentials vault |

Snow Gloves retains canonical workflow authority; OpenAI resources are adapter
bindings. Local CLI/OmniRoute adapters implement the same logical contracts,
without assuming they can import OpenAI-native sessions or use its managed harness.

## Environment admission

Choose no-compute remote-MCP, OpenAI-hosted Linux sandbox, or self-hosted executor
based on task requirements. Verify availability of each mode before assignment.
OpenAI's self-hosted model uses an outbound `codex exec-server` connection; each
session needs its own environment ID and executor. Map those to resource slots.
Do not assume moving a session transparently relocates its sandbox or filesystem.

Isolate execution per brand/workload with an actual OS/container/VM boundary or
reviewed equivalent: a worktree/directory alone is not credential isolation.
Application API keys remain outside executors. Executors receive dedicated
restricted connection keys and only job-required capabilities. No shared founder
home directory, all-brand dotenv, native session cache, or iCloud live database.

## Credential design

For remote managed MCP calls, attach a dedicated scoped MCP access credential
bound to the exact server URL. Prefer a token for the Snow Gloves governed tool
gateway over exposing upstream provider administrator keys. Gateway enforcement
still checks caller, organization, brand, action, approval, and budget.

Attach vault/credential refs only after admission; metadata or possession of an
ID does not confer access. One-way explicit provisioning from the selected secret
source is preferable to automatic bidirectional sync between vaults. Never include
secret values in agent definitions, planning packets, traces, or handoff files.

Environment credentials have distinct host-injection and network-access rules;
configure both where supported. Verify credential support per environment type.
Rotation is not automatically applied to an existing sandbox: official guidance
requires a new session for replaced environment credentials. Drain/recreate and
re-probe affected environments. Revocation enforcement remains server-side.

## Persistent workflow and handoff protocol

1. Admit a trigger under verified scope; deduplicate its workflow identity.
2. Resolve agent/environment/tool versions and credential refs; reserve resources.
3. Create or continue the permitted session; persist mapping before dispatch.
4. Track turn/events/results with replay cursor and correlation IDs.
5. On handoff, stop/drain or reach a supported safe boundary; record pending and
   in-doubt tools before committing a checkpoint.
6. Fence old execution ownership. Package accepted plan/source/artifact digests,
   workflow step, policy version, event cursor, environment requirements, and
   credential *references*. Provider resource IDs stay in restricted backend state.
7. Re-authorize the destination and provision fresh required credentials. Same
   supported session may continue; otherwise create a linked successor with
   approved context. Never claim cross-provider native history migration.
8. Verify workspace/artifacts/current policy, acknowledge transfer, then resume.
   A failed destination leaves a visible blocked transfer; no duplicate executor.

Conversation continuity, filesystem continuity, credential continuity, and action
authority each need separate proof. Compacted session context is not the canonical
business memory or substitute for artifact checksums and accepted plans.

## Event-driven agents and fleet display

Version the existing Snow Gloves roles in an agent registry. Triggers and durable
workflow logic wake bounded agent turns; skills remain capabilities used within
those turns. Persistent does not mean perpetual inference. Avoid one enormous
session holding every brand; scope sessions to work streams/campaigns.

Session World shows adapter, agent version, environment/node, credential readiness
without values, turn/step state, last event age, handoff and pending approval.
Normalize streamed events/webhooks; export traces only with explicit permission
and redact/minimize data before fleet ingestion. Provider traces are evidence,
not canonical action admission or successful campaign delivery.

## Acceptance and roadmap joins

Dependencies: #18 RBAC, #19 secrets, #20 runtime, #22 control plane, #23 handoff;
feeds #25 visualization and #28 load acceptance. Bootstrap inventories executor
versions/environment profiles; doctor checks identity, session mapping, executor
ownership, credential-reference readiness, replay, rotation and expiry separately.

First pilot: one brand, one agent, synthetic tool, restart/resume, artifact readback.
Negative tests: wrong-org attachment, expired credentials, deleted/missing workspace,
revoked destination, duplicate trigger, lost executor, stale policy, tampered
checkpoint, changed agent definition, rotation with old sandbox, and unknown tool
outcome. Test 50-session admission only after executor memory/quota measurements.

## Official references

- https://developers.openai.com/api/docs/guides/agents-api/overview
- https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted
- https://developers.openai.com/api/docs/guides/agents-api/tools/mcp
- https://developers.openai.com/api/docs/guides/agents-api/tools/vaults
- https://developers.openai.com/api/docs/guides/agents-api/sessions/manage
- https://developers.openai.com/api/docs/guides/agents-api/tracing

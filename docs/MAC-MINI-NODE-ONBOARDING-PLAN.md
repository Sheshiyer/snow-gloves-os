# Fresh Mac mini node — CLI onboarding plan

Status: planning candidate, 2026-09-30. No bootstrap CLI or installation is
implemented by this document. Extends the remote workspace draft kept in the
private ops repo (`snow-gloves-ops/docs/AXTECH-REMOTE-WORKSPACE-DRAFT.md`).

Detailed bootstrap, doctor, debug, RBAC, and handoff contracts:
[feature spec](../specs/005-node-bootstrap/spec.md),
[implementation plan](../specs/005-node-bootstrap/plan.md), and
[tasks](../specs/005-node-bootstrap/tasks.md).

## Intended experience

The owner starts with a fresh Mac mini, signs in to the
shared Apple account, installs and signs in to Claude Code, and opens a trusted
Snow Gloves release README. The README provides the start prompt in
prompts/mac-mini-node-start.md. Claude drives a resumable, manifest-based CLI
bootstrap, reports verifiable results, and pauses only at necessary human steps.

There is a bootstrap prerequisite: a machine cannot run Claude's start prompt
until Claude itself and access to the README exist. Document one supported
manual entry path for Claude, macOS administrator approval, and downloading the
verified release. Do not assume Node, Git, Homebrew, or shell credentials already
exist merely because Claude is signed in.

Apple identity, Claude identity, GitHub identity, node identity, Cloudflare
identity, vault enrollment, and brand authority are separate. The shared Apple
account does not enroll a node or authorize a connector. Do not synchronize
runtime directories, live databases, OAuth caches, or dotenv secrets through
iCloud. Every mini receives a distinct device key and revocable permissions.

## Layer 0 — preflight and machine identity

- Discover chip, RAM, free disk, macOS version, architecture, network, existing
  tooling, and existing services; never assume the node is empty without checks.
- Select coordinator, worker, or recovery role and a unique node alias.
- Define workspace and artifact locations outside cloud-synchronized folders.
- Check command-line developer tools, administrator access, time synchronization,
  FileVault status, power/sleep policy, and remote recovery prerequisites.
- Capture current configuration before changes. Maintain a redacted checkpoint
  ledger, ownership manifest, and explicit rollback instructions.

## Layer 1 — development foundation

Resolve supported versions from a reviewed release manifest, rather than
installing every tool's latest version independently.

| Component | Purpose and install rule |
|---|---|
| Apple command-line tools | Git/build prerequisites; full Xcode only for a selected native build role |
| Homebrew | Apple Silicon package management; verify source and architecture |
| Node + npm | Supported LTS runtime, package lockfiles, explicit global-tool policy |
| Bun | Projects that declare Bun; preserve npm lockfile ownership elsewhere |
| Python + uv | Isolated project environments and locked dependencies; leave system Python alone |
| Git + GitHub CLI | Repository access, distinct SSH/device keys, separately verified authentication |
| curl, jq, ripgrep, make, archive utilities | Bootstrap, diagnostics, structured API work, search, builds |
| tmux | Persistent operator terminals; not a substitute for service supervision |
| Playwright browsers | Optional browser-worker role, installed with the pinned project version |
| ffmpeg and image utilities | Optional media-worker role; verify requested codecs and disk budgets |
| Rust / full Xcode / containers | Optional native-build or container role, not every node |

Verify binaries and versions in a fresh login shell. Use absolute resolved
executables in services because launchd does not inherit interactive shell PATH.
Do not overwrite shell configuration; make owned additions and preserve backups.

## Layer 2 — operating runtime

- Install a pinned Temperance release with its supported dependency/hook manifest.
  Verify installed CLI behavior separately from source/package availability.
- Capture the current OmniRoute version and configuration model first. Provision
  reviewed routing on the coordinator; worker nodes use authenticated access
  unless a separate router is justified. Never copy native subscription sessions.
- Install project-scoped Wrangler/Cloudflare tooling and verify the exact
  `<cloudflare-account>`; Cloudflare authentication is distinct from production deployment.
- Install Snow Gloves and render only verified Claude/runtime adapters.
- Enroll the node with the secrets service; retrieve role/brand-scoped values.
  Enable the dotenv save listener only on an explicitly selected writer node.
- Supervise required services with launchd, ownership manifests, dependency order,
  backoff, logs, and health checks. Choose user-agent versus system-daemon mode
  deliberately; test keychain access and encrypted-disk reboot behavior.
- Connect protected remote access, durable jobs, node heartbeats, leases, resource
  reservations, and application-level authorization.

## Layer 3 — capabilities and brand onboarding

Install MCPs and connectors from reviewed catalogs with versions, tool lists,
credential references, scopes, health probes, and per-brand admission. Discovery
does not enable tools. Credentials never appear in MCP JSON, prompts, or logs.

Prepare selectable packs: repository/build, research/browser, lead discovery,
enrichment, CRM, email/calendar, analytics, advertising, and paid media generation.
GetLeads and Explee identities and API contracts must be verified before live use.
Connectors for generation, ad publishing, and campaign delivery have separate
permissions; enabling a generation service does not authorize ad spend or sends.

Paid media jobs specify provider/model, maximum spend, asset rights/provenance,
brand brief, output format, retention, and review state. Persist remote job IDs
before polling and reconcile uncertain submissions rather than retrying blindly.
Use async queues, bounded polling, artifact checksums, and reusable result caches.

Map the portfolio's legal entities and brands, source-backed product/offer definitions,
approved senders/domains, budgets, contact-sharing policy, and suppression scopes.
Build first campaign drafts without live delivery. Do not infer brand ownership
or permissions from a shared Apple login.

## Layer 4 — operation and recovery

Add metrics for queue age, memory pressure, disk usage, service health, provider
errors, quota consumption, spend, and pending approvals. Logs redact secrets and
minimize contact and prompt data. Define retention and cache eviction before
large browser or media workloads fill the disk.

Encrypted backups need an independent recovery destination, offline recovery
material, database-consistent snapshots, and a demonstrated restore. Another
mini in the same location is useful but does not cover site-wide loss. Define
controlled updates, rollback, incident stop, maintenance windows, and fencing
for coordinator promotion. Confirm unattended recovery after power/network loss.

## Layer 5 — operator apps and agent CLIs

The final layer installs and verifies Codex desktop, Codex CLI, Claude Code CLI,
and the owner's selected Grok CLI distribution. Claude Code has two stages:
minimal installation/sign-in before the bootstrap prompt, then managed runtime
configuration and verification here. Do not defer its initial install until the
prompt that requires it.

| Surface | Required evidence |
|---|---|
| Codex desktop app | Verified distribution, installed version, launch, owner sign-in, correct workspace opening |
| Codex CLI | Verified package/version, shell discovery, independent authentication check, adapter and synthetic task |
| Claude Code CLI | Bootstrap entry preserved, version/auth check, scoped skills/MCP configuration, synthetic task |
| Grok CLI | Exact upstream/package identity confirmed before installation; version/auth and real command contract verified |

Render each runtime's supported instructions, skills, MCPs, and routing profiles
from the reviewed node manifest while preserving existing user configuration.
Keep one project authority and separate runtime-owned sessions. Shared Apple
login does not prove these tools share authentication. Do not assume desktop and
CLI auth parity or that every runtime supports the same MCP transports or
OmniRoute endpoint configuration; verify each supported integration separately.

Existing Grok adapter fields are unverified, so no package or install command is
assumed from the name alone. Offer additional runtimes as selectable catalog
items, not an automatic installation of every CLI on the host.

Provide node-level status showing tool version, authentication state, configured
workspace, connector admission, supported routing, and last bounded verification.
GUI apps are operator surfaces; supervised CLI workers handle unattended jobs.
Final acceptance opens the same workspace in selected apps and runs a harmless
synthetic task through every configured CLI without paid generation or outreach.

## CLI contract to implement

Proposed commands; none exist by virtue of this plan:

```text
snowgloves node inspect
snowgloves node plan --role coordinator
snowgloves node apply --plan <reviewed-plan>
snowgloves node resume
snowgloves node doctor
snowgloves node capabilities
snowgloves node verify --synthetic
snowgloves node rollback --checkpoint <id>
```

The plan resolves versions, destinations, owned files, actions, costs, auth steps,
and checks. Apply is idempotent: verified stages skip; failed stages resume;
partial success is explicit. No blanket sudo, destructive reset, or unbounded
upgrade. Each stage returns a secret-free receipt distinguishing installed,
authenticated, configured, running, connected, and behaviorally verified states.

## Acceptance and implementation sequence

1. Approve spec, plan, and tasks under the repository constitution.
2. Implement read-only inspection and planning, then foundation installation.
3. Implement resumability and rollback; test fresh-machine and partially
   configured-machine scenarios without touching this workstation.
4. Add runtime packages, vault enrollment, and supervised services.
5. Prove second-run idempotence, fresh-shell tool availability, reboot recovery,
   remote disconnect continuity, isolation, revocation, and backup restore.
6. Add a second worker and synthetic queue/lease/failure tests.
7. Enable chosen brand capability packs under bounded budgets and explicit
   external-action approvals. Existing approval persists; do not repeatedly ask.

macOS security dialogs, administrator credentials, interactive provider OAuth,
and trusted-device enrollment may require human interaction. The README must
identify those steps and offer resume, rather than promising unattended completion.

## Relationship to existing tooling

scripts/install.sh currently checks for preinstalled basics, installs Python
packages and a Paperclip CLI, and prints next steps. It is not a fresh-machine
bootstrap, daemon manager, vault client, or live campaign setup. Keep its existing
path intact until the new workflow passes acceptance. Paperclip CLI installation
does not establish a running Paperclip server. Existing MAC-MINI-SETUP.md remains
the bounded first-hour guide; this plan is the future node operating workflow.

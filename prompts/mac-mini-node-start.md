# Fresh Mac mini — Claude start prompt

Planning prompt for the future CLI workflow. The node CLI is not implemented
yet; do not claim these instructions can currently complete onboarding.

Copy the following into signed-in Claude Code in a verified Snow Gloves checkout:

```text
Help me onboard this Mac mini as a Snow Gloves OS node for my brand portfolio.
Start by reading AGENTS.md, .specify/memory/constitution.md, and
docs/MAC-MINI-NODE-ONBOARDING-PLAN.md. Instance data (brand tenants, fleet.yaml,
nodes/) lives in the private data checkout named by SNOWGLOVES_DATA; read it
there if it is mounted, and never copy it into this checkout.

Assume I have signed in to my Apple account and Claude, but inspect the machine
before assuming any other tool, service, account, or credential is available.
Inspect chip, RAM, disk, macOS, network, installed binaries, and existing config
without printing credentials or provider session material. Confirm this node's
unique identity and coordinator/worker/recovery role. Preserve existing files.

Prepare a resumable plan from a reviewed release manifest for developer tools
(Node/npm, Bun, Python/uv, Git, and essential utilities), then Temperance,
OmniRoute, Cloudflare tooling, Snow Gloves, protected remote access, and secrets
enrollment. Install optional browser/media/build tooling only for selected roles.
Use project environments and lockfiles; do not modify system Python.

Finish with the operator layer: Codex desktop app and CLI, Claude Code CLI,
and my selected Grok CLI. Verify distribution identity, version, sign-in,
workspace access, supported routing, and runtime-specific adapters independently.
Claude is already the bootstrap entry point; complete its managed configuration
here. Confirm the exact Grok upstream/package before installing it. Preserve
user configuration and keep runtime sessions separate. Test harmless synthetic
tasks, not live paid provider operations, as onboarding proof.

If the documented node CLI is unavailable, report that accurately and produce
the missing implementation plan rather than inventing working commands. Respect
the repository's approved-spec/plan/tasks prerequisite for implementation.

Use separate device credentials and scoped vault profiles; never copy another
machine's native login stores or entire dotenv file. A shared Apple account
does not grant connector or brand permissions. Keep owned runtime data outside
iCloud-synchronized directories. Never paste secret values into chat or logs.

Set up verified modules through the tenant connector gate. Treat GetLeads,
Explee, paid media generation, ad publishing, and campaign delivery as distinct
capabilities. Live paid calls and external sends require their specific existing
authorization; preparing a dry run does not authorize execution.

Verify each layer separately and save redacted checkpoints. Test idempotence,
restart/reboot behavior, remote continuity, resource limits, backup restore,
and synthetic jobs before calling this node operational. When a macOS dialog,
sudo credential, provider login, or device approval needs me, explain the exact
step and resume from the checkpoint afterward. Do not repeatedly seek approval
for actions already authorized. Finish with installed/configured/running/verified
states, remaining human steps, and the next resumable command.
```

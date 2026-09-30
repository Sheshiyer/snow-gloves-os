# Axtech remote workspace — architecture draft

Date: 2026-09-30. Status: proposal, not implemented or approved for activation.

## Owner intent

Run the existing OmniRoute on an always-connected Mac mini, operate Snow Gloves
OS remotely, and distribute work across two or three minis. Connect GetLeads
and Explee for campaign operations across Axtech brands, initially HeyZack,
Ecoled, and Kartezzi. Brand spellings and legal/company relationships require
source-backed mapping. These are proposed scopes, not provisioned tenants.

## Topology

- Primary mini: Snow Gloves operator surface, job coordination, authoritative
  campaign state, Hermes events, and the existing OmniRoute candidate.
- Second mini: leased jobs for research, enrichment, indexing, and draft creation.
- Optional third mini: artifact processing, backups, and recovery rehearsal.
- Cloudflare account alias `9d9d`: authenticated access edge and encrypted
  secrets-sync service. Confirm full account identity before resource creation.
- Remote laptop: operator client; heavy tasks continue on the minis after the
  laptop disconnects.

Roles depend on actual chips, RAM, disks, connectivity, and existing services.
Owner reports M4 and 512 GB storage; confirm whether this applies to every
mini. RAM, exact node count, locations, and network links remain unknown.
Set concurrency after measured memory pressure and per-job resource usage.
RAM remains machine-local; aggregate capacity means parallel independent jobs,
not a single shared-memory machine. Provider quotas and budgets also remain
separate from hardware capacity. Do not multiply subscriptions or share native
login stores as a substitute for supported provider authentication.

Use authenticated private networking for SSH and node traffic, and a
Cloudflare Tunnel plus Access-protected application for browser access. Do not
expose an unauthenticated OmniRoute endpoint. Access is an outer gate; the
application must still enforce user, device, tenant, and action permissions.

## Operating boundaries

OmniRoute owns inference routing, not job durability or campaign permission.
Snow Gloves owns interpretation, dispatch, connector admission, and audit.
Add durable job storage, leases, heartbeats, resource reservations, deadlines,
retry limits, and deduplicated results. On lease expiry, unfinished computation
can be reassigned. A campaign send with an uncertain outcome must reconcile
the provider receipt before any retry; never blindly replay it.

Start with one authoritative coordinator and tested backups. A second machine
is not automatic high availability: failover needs an explicit promotion and
fencing procedure to prevent two coordinators or senders operating concurrently.
Do not share a live SQLite database over a filesystem mount.

Always-on operation requires supervised services, restart limits, startup
ordering, sleep policy, encrypted-disk/unattended-reboot verification, log
rotation, disk alerts, and restore tests. The current Mac Mini first-hour guide
uses foreground Hermes and is not evidence for these capabilities.

## Portfolio and campaign model

Axtech is the proposed portfolio scope. Each brand gets an isolated knowledge
corpus, connector permissions, credential namespace, campaign budget, sending
identity, contact access policy, and audit trail. Legal entities may own multiple
brands; map that relationship without collapsing brand permissions.

Cross-brand campaigns explicitly name participating brands, lead-sharing rules,
selected offer, sending identity, budget, and owner approval. Shared account
research can be deduplicated without granting every brand access to all personal
contact data. Define portfolio-wide contact-frequency coordination and the
applicable brand/channel/global suppression scopes before outreach.

Campaign loop:

```text
approved brand sources → ICP/offer brief → approved search budget
→ GetLeads/Explee adapter → normalized candidates with provenance
→ deduplication and brand-fit scoring → suppression checks
→ draft campaign → exact audience/content/channel approval
→ authorized delivery adapter → receipts/replies → brand learning
```

GetLeads product identity and API contract remain unverified. Explee has a
catalog pack and an existing brand-enriched AutoGTM specification; those do not
prove configured credentials or current live provider compatibility. Discovery,
enrichment, and delivery are separate capabilities. Do not assume either lead
provider delivers outreach.

Use the existing connector-gate and per-tenant enabled-module/approval records.
Provider results normalize into platform-owned records so providers remain
replaceable. Every candidate retains source, acquisition time, provider record
reference, and permitted-use metadata.

## Secrets integration

Keep the Claude dotenv workflow as an approved ingestion surface. Ship scoped
local retrieval first, with provider proxy support planned next. Enrolled minis
receive only job-required namespaces. Avoid syncing the entire founder env to
every node. Machine trust, vault access, and brand permissions are independent.
Local-only records are encrypted for approved devices. Future proxy credentials
require explicit server-decryptable envelopes and invocation permissions.

## Delivery lanes

The fresh-machine CLI, README entry, and Claude start-prompt workflow are
specified in [MAC-MINI-NODE-ONBOARDING-PLAN.md](MAC-MINI-NODE-ONBOARDING-PLAN.md).
This adds the requested tooling, runtime, capability, and recovery layers.

1. Inventory minis and existing OmniRoute version, configuration references,
   supported authentication, health checks, backup, and rollback. Do not migrate
   provider state until this evidence is reviewed.
2. Specify one-node remote pilot: supervised services, authenticated remote
   access, synthetic vault credentials, one isolated brand, and local drafts.
3. Prove reboot, disconnect continuity, restore, tenant isolation, revoked-device
   rejection, resource limits, and zero unauthorized external actions.
4. Add one worker; prove lease expiry, resource scheduling, duplicate-result
   rejection, and uncertain-outcome reconciliation.
5. Map Axtech brands from canonical sources and enable verified lead adapters
   under explicit paid-call budgets. Produce reviewed prospecting drafts.
6. Introduce approved delivery channels and cross-brand campaigns only after
   suppression, sender, audience, approval, and receipt contracts pass.

Before implementation, produce approved spec.md, plan.md, and tasks.md under
the repository constitution. This draft does not approve deployments, startup
service installation, native-session migration, secret uploads, paid calls,
connector activation, or campaign sends.

## Source anchors

- AGENTS.md and .specify/memory/constitution.md
- docs/MAC-MINI-SETUP.md
- skills/connector-gate/SKILL.md
- specs/004-brand-enriched-autogtm/spec.md
- catalog/cards/explee-skills.md
- https://developers.cloudflare.com/use-cases/apis/internal-services/

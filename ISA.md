---
task: "Source binding, capability proof and measured fleet acceptance"
project: snow-gloves-os
effort: E5
effort_source: classifier
phase: execute
progress: 24/51
mode: interactive
started: 2026-09-30
updated: 2026-10-05
---

## Problem

Current continuation: tenant contexts and matching research are bound into verified source plans; sandbox renders, selected host connector reads and company Cloudflare scope are verified. Physical wing jobs, gateway runtime, eventing, recovery and capacity acceptance remain open. The September pilot below is retained as a historical delivery lane, not evidence that the broader fleet works.


Two attempts at the foundation workers produced no implementation. The legacy
installer changes global Python packages, and legacy diagnostics confuse an open
port with service identity. The confirmed installation target for 1 October is
one Mac mini running a local bootstrap and recovery pilot.

## Vision

The operator can trace a brand-specific source through an admitted capability, scoped wing execution and a verifiable artifact. Fleet readiness records distinguish source, sandbox, installed host, actual device and cloud acceptance.


The operator can unpack a reviewed bundle, inspect the mini, review a digest-bound
plan, apply it, and demonstrate safe resume and rollback. Readiness reports make
the local pilot useful while showing the live-service requirements still held.

## Out of Scope

- Live provider activation, credentials, organization enrollment, and campaign delivery.
- Cloudflare deployment and remote service activation without the recorded account/domain and action gates.
- New third-party enablement, external sends or credential mutation inferred from a capability inspection.
- Claims of a completed reboot, restore, or fresh Mac installation without device evidence.

## Principles

- Report evidence separately for source, local installation, and the physical mini.
- Default inspection and diagnostics to read-only behavior.
- Roll back only files whose ownership and current bytes are verified.

## Constraints

- Use Python standard library for the pilot entry path; require Python 3.10 or later.
- For the historical pilot implementation, preserve its pinned free Command Code rail; no paid or Sol fallback without the recorded override.
- Preserve existing enabled-module authority and installed host runtime configuration during sandbox proof.
- Bind sources inside their named tenant; keep private instance data in the private checkout.
- Preserve unrelated remote checkout edits and record exact provenance before device changes.
- Bind apply and resume to the reviewed plan and source digest.

## Goal

Bind the existing portfolio records to source-linked tenant knowledge, prove admitted capabilities through actual runtime outputs, and complete measured physical fleet acceptance including eventing, recovery, the selected company gateway and session/resource acceptance. Keep every requirement open until its own current evidence proves it; the historical pilot remains a contributing lane with stable criteria.


Deliver a source-tested local pilot with inspect, plan, apply, resume, status,
doctor, debug collection, and rollback. Produce a checksum-verifiable installation
bundle and a runnable 1 October mini runbook; record device acceptance as pending
until the actual mini supplies evidence.

## Criteria

- [ ] ISC-1: Inspect emits structured hardware and tool-presence evidence.
- [ ] ISC-2: Repeated plan generation produces the same digest for the same inputs.
- [ ] ISC-3: Invalid CLI invocation exits 3.
- [ ] ISC-4: Anti: inspect and default doctor create no files.
- [ ] ISC-5: Apply rejects a mismatched reviewed digest.
- [ ] ISC-6: Apply rejects a changed source digest.
- [ ] ISC-7: Concurrent mutation is rejected by a node lock.
- [ ] ISC-8: Stage journal writes use atomic replacement.
- [ ] ISC-9: Second apply produces no duplicate effects.
- [ ] ISC-10: Resume rechecks bytes of completed stages.
- [ ] ISC-11: Interrupted write can be reconciled safely from the journal.
- [ ] ISC-12: Rollback removes only installer-owned files with matching bytes.
- [ ] ISC-13: Drifted files keep rollback in manual recovery.
- [ ] ISC-14: Anti: path traversal and symlink targets cannot escape the pilot directory.
- [ ] ISC-15: Doctor reports unresolved live requirements as held.
- [ ] ISC-16: Debug collection uses an allowlist that excludes environment secrets.
- [ ] ISC-17: Local installer supports a dry-run that creates no files.
- [ ] ISC-18: An isolated temporary installation executes the CLI lifecycle.
- [ ] ISC-19: The distributable bundle passes its checksum verifier.
- [x] ISC-20: Existing tests and catalog consistency checks pass after integration.

- [x] ISC-21: axio has a verified ingestion plan containing its existing tenant context.
- [x] ISC-22: axtech has a verified ingestion plan containing its existing tenant context.
- [x] ISC-23: cee-management has a verified ingestion plan containing its existing tenant context.
- [x] ISC-24: china-sourcing has a verified ingestion plan containing its existing tenant context.
- [x] ISC-25: ecoled has a verified ingestion plan containing its existing tenant context.
- [x] ISC-26: heyzack has a verified ingestion plan containing its existing tenant context.
- [x] ISC-27: izzimo has a verified ingestion plan containing its existing tenant context.
- [x] ISC-28: kartezzi has a verified ingestion plan containing its existing tenant context.
- [x] ISC-29: metagration has a verified ingestion plan containing its existing tenant context.
- [x] ISC-30: sunfeed has a verified ingestion plan containing its existing tenant context.
- [x] ISC-31: wave-concept has a verified ingestion plan containing its existing tenant context.
- [x] ISC-32: Selected instance ingestion paths resolve inside their named tenant.
- [x] ISC-33: Each imported matching-brand research snapshot has verified original-path and content-hash provenance.
- [x] ISC-34: External host-skill references are explicitly excluded from tenant ingestion.
- [x] ISC-35: Relative ingestion sources resolve through the configured private-data root in the CLI regression.
- [x] ISC-36: The unchanged public/default data-path contract passes its regression suite.
- [x] ISC-37: Every admitted HeyZack wing/runtime combination has a validated sandbox render receipt.
- [x] ISC-38: Each wing has an explicit cluster binding record that distinguishes host tier from device deployment.
- [x] ISC-39: Host pointer-capability checks prove the referenced files exist at the inspected host.
- [x] ISC-40: Selected admitted MCP read operations return actual scoped capability evidence.
- [x] ISC-41: Coding-wing doctor evidence is collected on the identified physical Coding Mac.
- [x] ISC-42: An admitted coding-wing job returns a source-scoped artifact and execution receipt on its physical device.
- [ ] ISC-43: An admitted marketing-wing job returns a source-scoped artifact and execution receipt on its physical device.
- [ ] ISC-44: An admitted design-wing job returns a source-scoped artifact and execution receipt on its physical device.
- [ ] ISC-45: A supervised Hermes round trip records interpretation, dispatch and artifact-linked completion.
- [x] ISC-46: The Cloudflare gateway plan passes scoped HeyZack account/domain isolation guards; AWS is deferred.
- [ ] ISC-47: The company cloud gateway passes real scoped-key and streaming acceptance from a fleet device.
- [ ] ISC-48: A physical recovery drill restores the reviewed configuration and owned artifacts.
- [ ] ISC-49: A durable session handoff survives interruption and resumes the same job identity.
- [ ] ISC-50: The required fleet session soak records accepted capacity with measured resource pressure.
- [ ] ISC-51: Anti: no source, sandbox or historical receipt is reported as physical or live acceptance.

## Test Strategy

| ISC | Type | Check | Threshold | Tool |
| --- | --- | --- | --- | --- |
| 1-4 | CLI | inventory, deterministic plan, bad flags, read-only snapshot | passing assertions | pytest + subprocess |
| 5-14 | recovery | digest/source mismatch, lock contention, crash reconciliation, drift, ownership, paths | deny unsafe state; preserve bytes | pytest + temporary directories |
| 15-16 | diagnostics | held findings and synthetic secret exclusion | no readiness promotion or leak | pytest + actual CLI JSON |
| 17-18 | install | dry-run snapshot and temporary prefix lifecycle | no global effects; runnable copy | shell + subprocess |
| 19 | package | checksum manifest over extracted contents | every digest matches | package verifier |
| 20 | regression | existing suite and catalog check | zero failures | make test; make catalog-check |

| 21-31 | sources | actual tenant ingestion CLI and plan readback | existing context present per tenant | CLI + JSON |
| 32-34 | boundaries/provenance | resolved path and digest audit | no cross-tenant or external ingest | filesystem/hash audit |
| 35-36 | regression | ingest CLI and data-path tests | zero failures | pytest |
| 37-40 | capabilities | sandbox manifests, binding records, host refs and admitted MCP reads | exact ids and actual outputs | CLI + filesystem + scoped MCP |
| 41-44 | physical wing execution | node-local doctor and artifact receipts | identified device and current source | SSH/CLI |
| 45 | supervised eventing | same job through interpretation and completion | durable event/artifact linkage | Hermes readback |
| 46-47 | cloud | spec 008 guards, scoped calls and streaming | selected company target accepted | guard CLI + real requests |
| 48-49 | recovery | controlled interruption, restore and resume | source/job/owned bytes preserved | device lifecycle probe |
| 50 | capacity | existing fleet/session acceptance target | measured soak meets contract | resource/session receipts |
| 51 | claims | receipt evidence-level audit | no readiness promotion | receipt audit |

## Features

| Name | Description | Satisfies | Depends on | Parallelizable |
| --- | --- | --- | --- | --- |
| PilotCLI | inspect, plan, doctor, debug, lifecycle entry | ISC-1..4,15..16 | contract | yes |
| RecoveryJournal | digest-bound atomic mutation and rollback | ISC-5..14 | contract | yes |
| InstallationKit | isolated install and checksum bundle | ISC-17..19 | contract, then integration | yes |
| Regression | full source acceptance and runbook | ISC-20 | preceding features | no |

| SourceBinding | tenant context and matching-source provenance | ISC-21..36 | existing intake | yes |
| CapabilityProof | admitted sandbox matrix and real host reads | ISC-37..40 | SourceBinding | yes |
| PhysicalFleetAcceptance | wing jobs, eventing, cloud, recovery and session/resource evidence | ISC-41..51 | CapabilityProof and existing specs 005/007/008 | no |

## Decisions

- refined: 2026-10-05 — Founder explicitly deferred all HeyZack AWS work. Use the existing scoped HeyZack Wrangler setup and company zone hey-zack.fr. Withdraw AWS account/SSO prerequisites. Verify CLI account/zone scope and select a compatible Cloudflare runtime before deployment; old EC2 implementation is historical.

- 2026-09-30: User selected one Mac mini local bootstrap, doctor, resume/rollback pilot for 1 October.
- 2026-09-30: Review checkpoint claims against actual worktree changes and structured tool receipts before integration.
- 2026-09-30: The old free workers had repeatedly explored legacy approval flows. Restart bounded implementation outside inherited repository-agent context, retaining isolated outputs and the exact free model.
- 2026-09-30: ISA and ReReadCheck selected for analytical scope and final ask compliance. External isolated workers implement separate file ownership contracts.

- 2026-09-30: Advisor on the same free pin highlighted interruption ordering, fsync failure, path confinement, source drift, and lock release after termination. Device power-loss durability remains a physical pilot gate.
- 2026-09-30: Tool-loop retries inspected their own logs; switched to one-response source generation with all context inline and controller-run tests.

- 2026-09-30: Native routing override remains pending. Draft runbook/tests moved under .planning/pilot-drafts; inactive Make targets removed. All source jobs stopped; no accepted implementation.

- 2026-10-05: refined: active user goal extends acceptance to source binding, capability proof and measured fleet acceptance. ISC-1..20 remain unchanged; new scope is ISC-21..51. Private execution contract is specs/009-source-capability-fleet-acceptance in the instance checkout.
- 2026-10-05: Interview intake reused the explicit three-part objective and prior review. No further scope choice is needed for local source binding or sandbox proof; company gateway domain/account and new enablements remain pending inputs.
- 2026-10-05: Ingestion checkpoint: undefined relative-path root is the data seam defect. Resolve through data_root rather than patching each manifest with host-specific absolute paths.

## Changelog

- 2026-10-05 | conjectured: imported source registrations could feed ingestion through the private-data seam.
  refuted by: CLI regression reproduces NameError for a relative source path.
  learned: root resolution was lost at the public/private split and helper-only tests did not exercise the entrypoint.
  criterion now: ISC-35 requires a real CLI regression across the private-data seam.

## Verification

Baseline before new implementation: `python3 -m pytest -q` returned **138 passed in 5.85s**.
Fresh-machine, reboot, and restore verification remain pending on the actual mini.

- ISC-35: CLI regression — new test failed with NameError before the repair, then passed against a temporary private data root.
- ISC-36: data-path regression — ingest CLI, filters and paths suite reported "15 passed in 0.19s".

- ISC-21..31: ingestion CLI and JSON readback — eleven tenant plans each contain all seven existing context files.
- ISC-32: resolved-path audit — 87 selected files; zero cross-tenant paths and zero unintended skips. Ten JSON provenance/evidence sidecars are intentionally excluded from Markdown ingest.
- ISC-33: hash audit — five matching-brand snapshots, each original dossier and evidence file byte-identical to its tenant-local copy.
- ISC-34: manifest readback — external HeyZack brand-pdf-skill reference now has ingest: false.
- ISC-37: render manifest/hash audit — all twelve admitted HeyZack wing/runtime combinations match enabled intersections in isolated sandbox outputs.

- ISC-38: indexed binding readback — twenty explicit wing-to-cluster entries retain host tier and node-deployment status; deferred clusters are not claimed deployed.
- ISC-39: canonical pointer paths — superpowers, gsd and taste-skill host SKILL.md references all exist. This proves host file presence only.
- ISC-41: physical SSH doctor — source 7bcbbb9 on Coding Mac; doctor exit 1 after 35.83 seconds. Tailscale, node profile and eleven manifests pass; gateway/Hermes fail. Collection is complete, operational acceptance is not.

- ISC-20: full current regression suite — 305 passed in 11.65s; catalog up to date. This does not prove the missing historical pilot implementation.
- ISC-40: admitted GitHub connector returned exact repository metadata and VERSION content/blob SHA; host connector transport recorded separately from the device npm server.
- ISC-46: Cloudflare-only guard passed authenticated pinned identity/account/active-zone readback; 15 rejection/secret-suppression tests pass. Target and guard receipt stay private. Deployment/runtime acceptance remains ISC-47.

- ISC-42: physical mac-coding.local executed admitted github-mcp over stdio without credentials, retrieved VERSION and two source files with verified Git blob hashes, wrote source-audit.json and receipt.json in its isolated proof directory. Independent SSH artifact readback matches SHA256 beb423008d4af43b26fd1def5af1270bd4ea738905ac50279e044413b7c29912. Deprecated npm server and unpublished main-branch ingestion defect remain recorded findings; gateway/agent-model execution is not claimed.

- 2026-10-05 capability refinement: deprecated GitHub npm launcher replaced by official native stdio launcher in source card and public/private coding profiles. Fresh sandbox-github-official outputs verify all twelve combinations; 82 catalog/node/adapter/onboarding tests pass. Initial reuse of existing sandbox exposed adapter merge-fragment behavior; new empty sandbox avoids falsely accepting a stale installed config. Official device binary/auth remain pending.

- 2026-10-05 official binary evidence: GitHub MCP v1.14.0 Darwin arm64 archive matches upstream SHA256 e3baa88424ecc24ae504a1c98c128823fc2c2edbe9dd64e1456f39edea701140. Isolated physical Coding Mac binary reports 1.14.0 and stdio/read-only help passes. Company authentication and live runtime binding remain pending; no OAuth flow started.

- 2026-10-05 source reconciliation: bound a historical HeyZack Shopify-shaped export (108 products, 146 variants, five blank SKUs) with byte-identical JSON/hash provenance and a Markdown identifier table. Two brochure copies are identical but have 87 shifted status fields; held from operational facts. Refreshed source-plan audit selects 89 tenant-local Markdown files; no raw product JSON, prices, stock or claims are ingested.

- 2026-10-05 runtime draft review: rejected the bounded producer draft because its production image substitutes a synthetic JSON server for actual OmniRoute/SQLite, container transport is incorrect, and recovery promotes readiness without installing restored bytes. Preserved only under private .planning/cloudflare-runtime-drafts/20261005-rejected; ISC-47 remains open.

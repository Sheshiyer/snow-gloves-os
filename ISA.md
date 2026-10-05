---
task: "Prepare one Mac mini local bootstrap pilot tomorrow"
project: snow-gloves-os
effort: E2
effort_source: classifier
phase: execute
progress: 0/20
mode: interactive
started: 2026-09-30
updated: 2026-09-30
---

## Problem

Two attempts at the foundation workers produced no implementation. The legacy
installer changes global Python packages, and legacy diagnostics confuse an open
port with service identity. The confirmed installation target for 1 October is
one Mac mini running a local bootstrap and recovery pilot.

## Vision

The operator can unpack a reviewed bundle, inspect the mini, review a digest-bound
plan, apply it, and demonstrate safe resume and rollback. Readiness reports make
the local pilot useful while showing the live-service requirements still held.

## Out of Scope

- Live provider activation, credentials, organization enrollment, and campaign delivery.
- Cloudflare deployment, remote service activation, and multi-node scheduling.
- Claims of a completed reboot, restore, or fresh Mac installation without device evidence.

## Principles

- Report evidence separately for source, local installation, and the physical mini.
- Default inspection and diagnostics to read-only behavior.
- Roll back only files whose ownership and current bytes are verified.

## Constraints

- Use Python standard library for the pilot entry path; require Python 3.10 or later.
- Preserve the pinned free Command Code rail; no paid or Sol fallback.
- Keep existing tenant and host runtime configuration untouched.
- Bind apply and resume to the reviewed plan and source digest.

## Goal

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
- [ ] ISC-20: Existing tests and catalog consistency checks pass after integration.

## Test Strategy

| ISC | Type | Check | Threshold | Tool |
| --- | --- | --- | --- | --- |
| 1-4 | CLI | inventory, deterministic plan, bad flags, read-only snapshot | passing assertions | pytest + subprocess |
| 5-14 | recovery | digest/source mismatch, lock contention, crash reconciliation, drift, ownership, paths | deny unsafe state; preserve bytes | pytest + temporary directories |
| 15-16 | diagnostics | held findings and synthetic secret exclusion | no readiness promotion or leak | pytest + actual CLI JSON |
| 17-18 | install | dry-run snapshot and temporary prefix lifecycle | no global effects; runnable copy | shell + subprocess |
| 19 | package | checksum manifest over extracted contents | every digest matches | package verifier |
| 20 | regression | existing suite and catalog check | zero failures | make test; make catalog-check |

## Features

| Name | Description | Satisfies | Depends on | Parallelizable |
| --- | --- | --- | --- | --- |
| PilotCLI | inspect, plan, doctor, debug, lifecycle entry | ISC-1..4,15..16 | contract | yes |
| RecoveryJournal | digest-bound atomic mutation and rollback | ISC-5..14 | contract | yes |
| InstallationKit | isolated install and checksum bundle | ISC-17..19 | contract, then integration | yes |
| Regression | full source acceptance and runbook | ISC-20 | preceding features | no |

## Decisions

- 2026-09-30: User selected one Mac mini local bootstrap, doctor, resume/rollback pilot for 1 October.
- 2026-09-30: Review checkpoint claims against actual worktree changes and structured tool receipts before integration.
- 2026-09-30: The old free workers had repeatedly explored legacy approval flows. Restart bounded implementation outside inherited repository-agent context, retaining isolated outputs and the exact free model.
- 2026-09-30: ISA and ReReadCheck selected for analytical scope and final ask compliance. External isolated workers implement separate file ownership contracts.

- 2026-09-30: Advisor on the same free pin highlighted interruption ordering, fsync failure, path confinement, source drift, and lock release after termination. Device power-loss durability remains a physical pilot gate.
- 2026-09-30: Tool-loop retries inspected their own logs; switched to one-response source generation with all context inline and controller-run tests.

- 2026-09-30: Native routing override remains pending. Draft runbook/tests moved under .planning/pilot-drafts; inactive Make targets removed. All source jobs stopped; no accepted implementation.

## Verification

Baseline before new implementation: `python3 -m pytest -q` returned **138 passed in 5.85s**.
Fresh-machine, reboot, and restore verification remain pending on the actual mini.

# 08. Company gateway — Cloudflare recovery lane

AWS has been deferred since the founder decision of 2026-10-05. The active design uses a Cloudflare Worker, one Gateway Durable Object, an owned OmniRoute container and a company R2 backup bucket. Account, zone, hostname, resource names and custody references belong in the private data checkout. The legacy EC2 modules remain historical source; their AWS commands are not the current bring-up procedure.

## Authority and evidence

Local implementation and synthetic recovery tests are authorized. `GATEWAY_START_ALLOWED=false` remains the deployment default. Publishing a branch or image, creating a PR, provisioning company credentials, deploying resources, selecting providers and running a Coding Mac canary require their separate recorded gates. Local Docker evidence does not establish Cloudflare deployment or physical fleet readiness.

Use the private target pins and named company authentication for the read-only scope check:

```sh
python3 scripts/fleet/cloudflare_scope.py --target "$SNOWGLOVES_DATA/specs/008-heyzack-cloud-gateway/cloudflare-target.json"
```

A successful scope check verifies identity/account/zone scope. It does not authorize deployment or prove streaming, backups or recovery. Keep inherited personal credentials and instance data outside the company runtime.

## Disk and readiness

[Cloudflare container disks are ephemeral](https://developers.cloudflare.com/containers/concepts/architecture/). A stopped container can restart from its image with an empty disk. The Durable Object stores orchestration state; encrypted checkpoint objects and their commit receipts live in R2. An active process or an open port is insufficient for inference readiness.

Startup must verify and restore the latest durably confirmed checkpoint before admitting inference. A temporary zero-provider runtime may initialize an empty disk solely to serve internal recovery operations. A missing, replaced, mismatched or undecryptable backup holds startup. It must never become an implicit empty bootstrap.

The explicit first-launch bootstrap gate is consumed durably once. Bootstrap uses zero providers and must export, commit and durably confirm its first encrypted checkpoint before traffic is admitted. Replaying the gate does not create a second empty instance. Provider activation remains a later human decision.

## Recovery contract

The Gateway serializes bootstrap, checkpoint, recovery and reviewed pruning. Durable Object storage records runtime generation, operation identity, progress and confirmed checkpoint references. Recovery retries within one generation reuse their restore identity; a genuinely new empty disk must install the checkpoint again.

An authenticated container-internal identity response binds the generation to the configured instance, immutable image and backup-key identifier. A recreated Durable Object may adopt an owned running container only after verifying that binding. Unknown or mismatched containers remain held. Identity responses never expose keys.

Recovery has a 120-second overall budget. Management handlers retain their existing 15-second deadline after headers, bounded 25–30-second probe calls and reviewed shutdown containment limits. Transient failures retry the same operation at most three times, with 60 seconds between attempts; the overall budget still applies. Verification failures remain held. A disconnected client ends its own wait while shared recovery continues for other callers.

Existing public inference routes and scoped-key behavior remain unchanged. Checkpoint, ciphertext export/import, restore and runtime identity are internal operations authenticated with the management role. Do not publish management mutation endpoints or reuse inference keys for management.

## Checkpoints and expiry review

While the owned runtime is active, checkpoint alarms run every 15 minutes. An alarm must not wake a stopped container merely to back it up. Checkpoint status explicitly reports failures or overdue work. The latest-good pointer advances only after the exported ciphertext, R2 object/commit versions, canonical context and durable confirmation have all been verified.

Completed checkpoints become eligible for expiry review after 24 hours. Eligibility does not authorize deletion. Always protect the latest good checkpoint regardless of age, active recovery references and active or held jobs. Present candidates for review before deleting backups.

Deletion requires ownership and exact object/commit version readback. The current R2 binding does not offer a version-conditional delete operation: reviewed pruning must account for this race and remain held if version exclusivity cannot be established. An uncertain deletion retains its durable record. Never report pruning success merely because a delete call returned. Both checkpoint registries currently cap at 256 entries; without an approved retention procedure, a 15-minute cadence reaches capacity in approximately 64 hours and then holds checkpoint creation before export. Resolve that procedure before a longer company soak.

## Keys and deployment overlay

Use a company password manager as recovery-key custody and a separate Cloudflare runtime secret as the runtime delivery channel. Planning files contain custody references and key identifiers only. Keep management, backend, storage-encryption, backup and scoped inference roles separate. Synthetic keys belong only in isolated local runs and are removed only after verified orderly cleanup.

Prepare the private overlay with company account/zone pins, a company backup-bucket binding, immutable image reference and runtime instance identity. Leave runtime start disabled. A local Docker image identity is distinct from a future published OCI manifest digest; record both only at their actual evidence level.

The narrow runner proposal must limit deployment and secret delivery to the company Worker, Durable Object, container image and backup bucket. A previously verified administrator profile is a scope reference, not an unattended runtime identity. Resource budget, recovery-key provisioning and rotation, provider selection, deployment and canary authority are resolved after the local packet is reviewable.

## Local acceptance packet

Run in Docker context `colima-sg-runtime-proof`, using isolated owned containers with no published host ports. Preserve the accepted image and receipts, the three original held volumes and migration-export containers. Remove additional proof volumes only after saved receipt ownership, labels and all running/stopped container mounts agree. Do not use shared prune commands.

The candidate image must contain every runtime core module, including identity handling. Receiver fixtures contain only ciphertext, manifest, receipt and a thin HTTP probe. Pin the image and verify bundled runtime hashes before execution.

Required proof includes a fresh source fixture and ciphertext with its synthetic key retained throughout the same execution; a native local R2 round trip with exact byte count, SHA-256, canonical context and object/commit versions; wrong-key held restore; correct-key recovery; same-volume fresh-container replay; and complete receiver disk loss followed by restoration into a new empty volume. Capture settled source database/content and process identity before receiver work and verify they remain unchanged.

Concurrency, Durable Object recreation, generation mismatch, bootstrap replay, wrong-key correction, retry exhaustion, interrupted confirmation, checkpoint scheduling, expiry protections, truncation, cancellation and deadlines require regression coverage. Core recovery and cleanup are separate outcomes. Acceptance requires both; uncertain cleanup retains owned evidence and exits unsuccessfully.

Record fresh TypeScript, runtime, controller and platform results separately from historical counts. Native local R2/Docker evidence remains local. Company streaming, physical wing execution, recovery, durable handoff and capacity/soak acceptance remain open until their complete contracts are demonstrated.

# Managed OmniRoute runtime image

Build from the platform repository root. The Dockerfile-specific ignore file admits only the selected runtime modules and packaging files:

```sh
docker build --platform linux/amd64 -f infra/cloudflare-runtime/Dockerfile -t snowgloves-runtime:3.8.50 .
```

The image pins Node 24 and verifies the published OmniRoute 3.8.50 archive checksum before installing its production dependencies. It runs a Python management service under `tini` as UID 1000. The launcher requires Linux, `tini` as PID 1, and the same process owner. Python uses isolated mode without bytecode writes. Trusted modules and crypto helpers are root-owned and read-only.

Supply an owned, canonical `/data` directory with mode 0700 and these runtime variables: `SG_INSTANCE_ID`, `SG_IMAGE_DIGEST`, `SG_BACKUP_KEY_ID`, `SG_BACKUP_KEY`, `SG_MANAGEMENT_KEY`, `SG_BACKEND_KEY`, and `STORAGE_ENCRYPTION_KEY`. The backup key is canonical base64 encoding of 32 independent bytes. All four keys must be distinct. The launch controller must bind `SG_IMAGE_DIGEST` to the immutable image it actually starts; an arbitrary environment value cannot prove that binding. Keep keys independently recoverable and outside source, image layers and command arguments.

Existing-state startup is the default and requires `storage.sqlite`. Fresh initialization requires explicit `SG_INITIALIZE_FRESH=1` and an empty data directory. Other values fail. The launcher uses `/tmp` as its home so emulation cache files cannot pre-populate the data directory before validation. Mount writable `/tmp` separately when using a read-only root filesystem.

The authenticated managed listener exposes port 8080; its actual OmniRoute child listens only on loopback port 8081. Management and backend credentials have separate roles. `/healthz` requires HTTP 200 and literal `ok` plus newline, and proves lifecycle only. Authenticated management readiness also remains separate from inference admission. Chat is held by the current production service policy; no provider connection or credential persistence patch is bundled.

## Local image evidence

On 2026-10-06 the owned Linux/amd64 proof exercised fresh and existing-state startup, actual encrypted checkpoint/restore, historical replay after restart, management-role rejection on backend models, held chat, SQLite integrity, zero providers and clean SIGTERM exits. The controller bound every request context to the exact Docker image identity. The measured image was 1,238,404,747 bytes. These results prove local packaging and lifecycle behavior; they do not establish company deployment, inference streaming, remote recovery or fleet capacity.

The build used a 6 GiB proof VM and a bounded 2 GiB npm installation heap. Initial container unpack failed when its 16 GiB data disk had only 2.5 GiB free; expanding that owned disk to 32 GiB allowed the proof to proceed. Those fixture settings are not a production sizing recommendation. The runtime child heap, concurrent workload pressure and durable storage budget require measured acceptance.

The Cloudflare transport currently requires a matching update for the managed port, required environment/context, initialization policy and repository-root Docker build context. Deploying its earlier raw-runtime configuration with this image is not accepted. Company account/domain pins and private receipts belong in the operations checkout.

## Encrypted checkpoints and owned files

`backup_crypto.mjs` uses Node built-in AES-256-GCM with an independent 32-byte key, fresh nonce and authenticated canonical metadata binding format, runtime version, image digest, key identifier and plaintext length. Decryption releases plaintext only after tag verification. The implementation buffers at most 64 MiB of plaintext; larger databases remain held. Run `make test-runtime-crypto` with Node 24+ and Python 3 for the owned SQLite fixture. Its 39 checks include a real 64 MiB boundary and independent decipher verification.

`backup_file_cli.mjs` accepts exactly `encrypt|decrypt`, an input leaf and a new output leaf. Its coordinator supplies `SG_BACKUP_ROOT`, `SG_BACKUP_KEY`, `SG_BACKUP_IMAGE` and `SG_BACKUP_KEY_ID` through a restricted environment. The helper confines access through an owned root descriptor, rejects symlinks, hardlinks and permissive inputs, verifies input bytes twice, and publishes through an exclusive 0600 temporary, file fsync, no-clobber hardlink, published-byte verification and directory fsync. Disputed post-publication outputs remain available for reconciliation. Run `make test-runtime-files` on Linux with Node 24+ and Python 3; 25 checks cover actual interruption and publication failures.

## Management and recovery

The bundled coordinator validates canonical request identity before effects, serializes mutation with inference handling, and checks root and executable identities. Its bounded CLI runner caps combined output at 4096 bytes and rejects timeout, nonzero exit, stderr and remaining owned descendants.

Checkpoint payloads carry `job_id` and canonical `request_digest`. Restore payloads carry a separate `restore_job_id`, `request_digest`, source checkpoint job and request digest, and the encrypted artifact leaf, byte count and SHA256. Trusted operation context contains `instanceId`, `runtimeVersion`, `imageDigest` and `keyId`.

Restore records durable mutation intent before changing the database. Interrupted mutation remains held after a fresh coordinator starts. Completion requires actual child health within ten seconds; completed-request replay returns a historical local record. A local completion does not imply current database identity or remote acknowledgment. Plaintext snapshots, recovery files and encrypted artifacts are retained; ownership-aware retention, artifact count/byte limits and free-space preflight remain necessary before unattended use.

Fresh initialization observes the service cancellation event. Shutdown serializes against management ownership; an exhausted cleanup wait relies on the verified PID-1 container boundary to remove the owned process namespace. Standalone process invocation is not an accepted containment substitute. Local SIGKILL checks establish process-interruption behavior, while power-loss durability, remote backup custody, physical recovery and same-job fleet resume remain separate gates.

The generic `runtime_storage_guard.py` component performs bounded read-only inventory and conservative byte, entry, class-count and available-space admission. Its 25 Linux fixture checks include sparse logical bytes, nested cache files, ownership and namespace races, deadlines and redacted failures. It is not yet wired into the coordinator or bundled in this image. A preflight cannot impose a hard filesystem quota on concurrent child writes; retention and cloud capacity remain separate acceptance gates.

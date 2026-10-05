# Isolated OmniRoute runtime image

Build the pinned published OmniRoute 3.8.50 package and its production dependency set for Linux/amd64:

```sh
docker build --platform linux/amd64 -t snowgloves-runtime:3.8.50 infra/cloudflare-runtime
```

The image runs the package server directly under `tini` as the non-root `node` user. It requires a nonempty `STORAGE_ENCRYPTION_KEY` supplied at runtime and an owned writable `/data` directory. Keep the key independently recoverable; it protects credential fields rather than encrypting the entire SQLite backup. Never put real credentials in build arguments, image layers or source files.

The health check requires HTTP 200 and the literal `ok` response from `/healthz`. This proves service lifecycle only, not authentication, provider availability or inference. No provider connection is bundled.

On 2026-10-05 an isolated Linux/amd64 image build passed with a 6 GiB build VM and bounded 2 GiB npm heap; the earlier 3 GiB build exhausted memory. The resulting image measured 1,225,676,445 bytes. Actual startup returned HTTP 200, SQLite quick_check passed with 131 tables and zero provider connections, and an owned test row and artifact survived container stop/start. Missing encryption-key startup was rejected. These are local image results, not a runtime sizing or fleet capacity recommendation.

The generic `backup_crypto.mjs` library encrypts a complete snapshot using Node's built-in AES-256-GCM with a caller-supplied independent 32-byte key, fresh nonce and authenticated canonical metadata. The metadata binds format version, runtime version, image digest, key identifier and plaintext length. Decryption returns plaintext only after tag verification. Wrong keys, mismatched context, malformed framing and tampering fail with a redacted error. This follows the [Node crypto API](https://nodejs.org/docs/latest-v24.x/api/crypto.html).

The library requires Buffer inputs and strictly validated context objects. It buffers at most 64 MiB of plaintext inside the container-facing Node process; do not run it in a Worker or treat that bound as accepted fleet sizing. Larger databases are held until a reviewed streaming implementation or measured sizing decision supports them. Key custody, replay policy and remote checkpoint acknowledgment are caller responsibilities still awaiting integration.

Run `make test-runtime-crypto` with Node 24+ and Python 3 for the owned SQLite fixture. Thirty-nine independent checks cover real SQLite roundtrip, a separate Node decipher, nonce variation, tampering, context/key/version rejection, strict object descriptors and size/framing limits, including actual encryption/decryption of a full 64 MiB payload. The exact helper also passed these checks on Linux/amd64 Node 24.21.0 in a network-disabled test container; its SQLite fixture was pre-created outside that container. This is crypto component evidence, not a remote recovery drill.

The Dockerfile does not yet bundle or invoke this library. Authenticated Worker/container transport, scoped-key streaming, independent encrypted backup and recovery, deployment and physical fleet acceptance remain separate requirements. The image does not yet include the platform lifecycle supervisor or an authenticated management endpoint. Company account/domain pins and private evidence belong in the operations checkout.

## Owned-file backup interface

`backup_file_cli.mjs` wraps the authenticated backup library for Linux Node24. It accepts exactly three arguments: `encrypt|decrypt`, an input leaf and a new output leaf. Supply the canonical owned directory in `SG_BACKUP_ROOT`, independent canonical base64 32-byte key in `SG_BACKUP_KEY`, image digest in `SG_BACKUP_IMAGE`, and key identifier in `SG_BACKUP_KEY_ID`. The key stays out of argv and output; the decoded buffer is cleared after the operation.

The interface confines files through an owned root descriptor, rejects symlinks, hardlinks and permissive inputs, bounds plaintext at64MiB, and verifies input bytes twice with exact metadata observations. Publication uses a0600 exclusive temporary, file fsync, no-clobber hardlink, actual published identity/byte verification, temporary removal and directory fsync before success metadata. A failed post-publication acknowledgment retains the disputed output for caller reconciliation. Actual SIGKILL tests prove interruption behavior without claiming power-loss durability or a completed job journal.

The runtime service must serialize operations in its restricted owned directory and reconcile artifacts by durable job identity. This helper does not provision R2, retain keys, decide replay policy or enable provider admission. The deployment Dockerfile does not yet bundle or invoke it. Run `make test-runtime-files` on Linux with Node24+ and Python3; `SG_FILE_SQLITE_FIXTURE` may point to an independently checked synthetic SQLite fixture when Python is outside the test image. Twenty-five Linux checks cover actual CLI roundtrip, failures, mutation, publication replacement and interruption.

## Management coordinator source

The generic Python components under `scripts/lib/` provide canonical operation identity validation, an authenticated management listener, bounded SQLite snapshots, a local checkpoint journal, a restore-intent store and `RuntimeManagementCoordinator`. The coordinator uses `runtime_bounded_process.run_bounded` to cap combined CLI stdout/stderr at 4096 bytes and reject timeout, nonzero exit, stderr and remaining owned descendants. It verifies recorded root and executable/script identities before effects.

`create_management_server` requires the trusted `operation_context` keyword containing `instanceId`, `runtimeVersion`, `imageDigest` and `keyId`. Checkpoint requests contain `job_id` and their canonical `request_digest`. Restore requests contain a separate `restore_job_id`, `request_digest`, `source_checkpoint_job_id`, mandatory `source_request_digest`, and the encrypted artifact's `leaf`, `bytes` and `sha256`. The listener validates these before its mutation gate or callback. Wire one coordinator's `checkpoint` and `restore` methods to the listener and share its operation gate with inference handling; inference integration is still pending.

A restore records durable mutation intent before invoking the supervisor. An interrupted mutation stays held after a fresh coordinator starts; it is not replayed automatically. Completion requires actual child health within a ten-second wait. A repeated completed request returns a historical local record without another restore. It does not establish current database identity, remote acknowledgment, power-loss durability or fleet session recovery. Plaintext snapshots and restore files are retained; a bounded ownership-aware retention policy remains necessary before unattended service use.

The components passed isolated Linux tests and an actual Node24/OmniRoute3.8.50 authenticated HTTP checkpoint/restore chain with zero providers and admission disabled. The probe used a synthetic image-context fixture. Production image binding, image packaging, service entrypoint, inference streaming, remote checkpoint storage and physical acceptance remain separate work. No company service is activated by importing these modules.

# Authenticated Cloudflare container transport

This generic Worker validates scoped wing keys and model access before reaching one fixed Durable Object. The object repeats validation before accessing the actual OmniRoute service through its container port binding. Model listing is local and reports permitted model IDs, not provider availability.

Install the pinned local toolchain, generate current runtime types, compile and test:

```sh
cd infra/cloudflare-transport
npm ci
npm run typecheck
npm test
```

Node 24 or newer is required for native TypeScript stripping in the component tests. The test suite uses synthetic keys, bounded streams and explicitly mocked container boundaries. It does not contact a provider or prove deployed inference.

Runtime secret bindings are `SCOPED_KEYS_JSON`, `MANAGEMENT_KEY`, `BACKEND_API_KEY`, `STORAGE_ENCRYPTION_KEY`, `SG_BACKUP_KEY` and `SG_BACKUP_KEY_ID`. The scoped registry holds SHA256 digests, a coding/marketing/design wing, exact model IDs and a valid UTC expiry. Raw client keys do not belong in source, configuration, logs or Durable Object storage. Management and backend credentials are separate from wing keys. Backend credentials must correspond to an independently created company runtime key; this source does not create keys or providers.

GET `/v1/models`, POST `/v1/chat/completions` and management-key GET `/_management/ready` are admitted. Authenticated `/v1/responses` stays held because the managed image does not implement it. Other UI, provider, raw health and management mutation routes are denied. Inference requests have an actual 1 MiB body limit and five-second read deadline. The Worker consumes the original body once and forwards the checked canonical JSON, rather than leaving an unread cloned-body branch. The upstream authorization header is replaced with the private backend key, response headers are restricted, and SSE bodies stream without buffering. Inference POSTs are never automatically retried.

The direct Durable Object Container API derives trusted image context from a digest-pinned selected image, injects all required independent keys and instance identifiers, and proxies through `getTcpPort(8080).fetch(...)`. The actual Node child remains on container loopback port 8081. Startup requires matching actual `inspect().image` and authenticated management readiness with exactly `{"ready":true}` in a bounded 16-byte JSON response. Raw health and `running` alone are insufficient. Caller cancellation and deadlines remain bounded even when a fixture ignores abort. `standard-1` remains an unaccepted runtime-size candidate.

The lifecycle manager remembers its own verified launch configuration in memory. An unknown running container after object restart, configuration drift, inspection failure or late readiness remains held; it is never recycled or destroyed automatically. A deployment whose generated image reference is opaque is held rather than assigned an invented digest. Publishing an explicitly digest-pinned company registry image requires its own authorization. Fresh initialization is absent by default; `GATEWAY_INITIALIZE_FRESH=1` maps to the image's strict empty-data initialization guard only for an explicitly reviewed instance. Container data loss is not authorization to initialize new state.

The Wrangler Docker build context is the repository root (`../..` relative to this configuration); the Dockerfile-specific allowlist admits only generic runtime inputs. No private tenant state or keys are build inputs.

The example keeps `GATEWAY_START_ALLOWED=false`, workers.dev and preview URLs disabled, one fixed gateway object identity, and contains no account IDs, routes or secrets. Authenticated runtime requests are held before backend access while the start gate is false; scoped model listing remains available. The durable_object scheduling policy does not support max_instances in the current CLI; fixed identity is a routing invariant, not a cloud billing cap. Company target pins belong in the private operations checkout and must pass its account/domain guard before an approved deployment.

The local managed image proves authenticated encrypted checkpoint/restore, but this Worker does not expose management mutation. Remote backup acknowledgment, recoverable key custody, bounded artifact retention and physical recovery are still required. The current management endpoint reports lifecycle only. Do not enable runtime start or admit provider credentials until those requirements and concrete cloud resource/budget approval pass. Local component and Workers-runtime evidence does not close physical scoped-key streaming, recovery, durable job resume or fleet soak acceptance.

## Standalone checkpoint commit helper

`remote-checkpoint.ts` accepts an explicit R2 binding, trusted context and the exact local artifact-verified journal record. It validates the canonical request digest before effects, uses native fixed-length streaming with byte/chunk/EOF limits, and verifies immutable ciphertext and canonical commit metadata/readback. Conditional collisions reconcile exact existing state. Its 30-second monotonic deadline and cancellation handling prevent client acknowledgment after a held outcome; an already submitted write may finish later and requires reconciliation.

The helper is not imported by gateway routes and no bucket binding is configured. Sixty transport tests and strict generated-type compilation pass. Actual local Workers/R2 fixtures also cover new commit, readback, replay and four invalid-body/checksum holds using synthetic ciphertext. This component evidence does not establish producer export, encrypted plaintext authentication, recoverable key custody, a company bucket, current provider credential durability or physical recovery.

### Standalone runtime export consumer

`export-remote.ts` binds an existing management checkpoint payload and trusted instance/image/key context to the fixed `http://runtime.internal:8080/_management/export` target through a supplied trusted fetch capability. It validates the exact export headers and journal record before calling the existing remote checkpoint helper. Its fixed 30-second total deadline includes digest validation, HTTP headers, streaming, R2 writes and readback; it propagates cancellation without retrying a POST or deleting an unknown late write.

Workers requires `redirect: manual`; exact status 200 rejects redirects without following them. Only the management bearer and JSON content type are sent. The portable `credentials: omit` option is retained; Workers has no browser cookie jar. Fetch exposes normalized headers, so validation rejects visible combined duplicates but cannot certify raw transport duplicates or duplicate JSON keys already collapsed by JSON parsing.

The stream adapter emits at most 64 KiB per pull with backpressure, retaining at most one host-delivered chunk. A larger backing allocation belongs to the host Fetch runtime; this is not an absolute 64 KiB resident-memory guarantee. It makes one streaming pass: the runtime verifies ciphertext before export, and native R2 checksum enforcement and immutable object/commit readback govern acknowledgment. Replay can cancel the unused HTTP body and still return a previously verified receipt.

Twelve Node regressions, strict generated Workers types, actual local workerd R2 adverse-body checks, and an owned localhost HTTP proof using 14,627,035 bytes exported from immutable image `e2afc6a8260453b73111331aa527ba33c92dd2f79a4ff9e2aa80746ea8258ef4` pass. The latter proves same-job object/commit version replay and complete local R2 readback. These are local fixture proofs. The consumer is not imported by the gateway entrypoint; no public management route, R2 binding, deployment, provider admission or physical acceptance is enabled by this component.

### Standalone remote receipt verification

`verify-remote-receipt.ts` verifies an encrypted object and canonical commit record through R2 `head`/`get`, using trusted copied checkpoint context and identity. An optional exact prior receipt also pins both object and commit versions. It validates native checksum metadata and the bounded commit body, then repeats both named-object heads after body verification. A fixed 30-second total deadline, late-response cancellation and a final check after cleanup govern acknowledgment. It makes no writes, deletes or runtime HTTP requests.

This proves observed consistency through final readback, not an atomic snapshot of two R2 objects or protection against future administrator replacement. Native checksum metadata does not prove AES authenticity; this verifier does not read the ciphertext body, download it into an owned runtime directory, decrypt or restore it. Twenty-one Node checks and actual local workerd R2 probes pass, including verification of the accepted image's 14.6 MB ciphertext and denials after object/commit mutations. The component remains standalone; durable job storage, runtime recovery, independent key custody and company/physical acceptance remain separate gates.

## Standalone durable confirmation helper

`durable-receipt.ts` confirms an existing remote checkpoint through one canonical registry string in SQLite-backed Durable Object storage. It validates copied input identity and optional receipt pins before writes, checks every stored job digest and receipt binding, reserves a prepared job transactionally, verifies R2 outside transactions, then confirms and synchronizes the same job before full registry readback. A replay independently verifies the pinned remote versions. Corruption, capacity exhaustion, missing state, replacement versions, cancellation or storage failures return a generic hold.

The registry has at most 256 sorted unique jobs, an 8 KiB bound per job and a 1 MiB total bound. One 60-second monotonic budget covers validation, storage, remote verification and cleanup. Already submitted storage operations may complete after a held result and require reconciliation. R2 observation and Durable Object confirmation do not form an atomic cross-service snapshot.

Twenty-two component checks and actual owned local SQLite Durable Object/R2 disposal and recreation prove same-job persistence and remote-version replacement rejection. The helper has no gateway route or resource binding and does not close cloud deployment, key custody, plaintext authentication or physical fleet acceptance.

## Standalone pinned ciphertext stream

`remote-cipher-export.ts` opens an explicit R2 ciphertext stream only after the unchanged remote verifier validates a mandatory receipt pin. It checks native get metadata, checksum, size and versions; counts exact bytes; emits views at most 64 KiB; and withholds the final chunk until actual EOF and a second pinned verification. A shared 30-second deadline covers opening, streaming, verification and cleanup. Cancellation also closes an unused stream. Returned metadata is copied separately from the internal pin and does not acknowledge body completion.

The receiver must independently count and hash the complete stream before publishing or decrypting it. R2 metadata checks do not authenticate plaintext, and sequential R2 observations are not a global atomic snapshot. Native host chunks may have larger backing allocations than emitted views. This component performs no remote writes or local file publication, adds no gateway route or bucket binding, and grants no restore or container adoption authority.

Twenty-two component checks, an actual owned local R2 export of the 14,627,035-byte image ciphertext with independent receiver SHA-256, and three native R2 replacement/missing-commit holds verify this seam. Cloud, key custody, local artifact import and physical recovery remain separate acceptance work.

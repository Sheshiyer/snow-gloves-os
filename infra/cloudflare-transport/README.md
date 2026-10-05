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

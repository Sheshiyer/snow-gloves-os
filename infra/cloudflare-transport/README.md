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

Runtime secret bindings are `SCOPED_KEYS_JSON`, `MANAGEMENT_KEY`, `BACKEND_API_KEY` and `STORAGE_ENCRYPTION_KEY`. The scoped registry holds SHA256 digests, a coding/marketing/design wing, exact model IDs and a valid UTC expiry. Raw client keys do not belong in source, configuration, logs or Durable Object storage. Management and backend credentials are separate from wing keys. Backend credentials must correspond to an independently created company runtime key; this source does not create keys or providers.

Only GET `/v1/models`, POST `/v1/chat/completions`, POST `/v1/responses` and management-key GET `/_management/ready` are admitted. Other UI, provider, raw health and management mutation routes are denied. Inference requests have an actual 1 MiB body limit and five-second read deadline. The Worker consumes the original body once and forwards the checked canonical JSON, rather than leaving an unread cloned-body branch. The upstream authorization header is replaced with the private backend key, response headers are restricted, and SSE bodies stream without buffering. Inference POSTs are never automatically retried.

The direct Durable Object Container API passes the storage key via `start({env: ...})` and proxies through `getTcpPort(8081).fetch(...)`. Startup is coordinated and HTTP readiness is reprobed; `running` alone is insufficient. Health must return HTTP 200 with exactly `ok` and a newline within a bounded 16-byte read. Caller cancellation and deadlines remain bounded even in the test fixture that ignores abort. `standard-1` is an unaccepted runtime-size candidate, not fleet capacity evidence.

The example keeps `GATEWAY_START_ALLOWED=false`, workers.dev and preview URLs disabled, one fixed gateway object identity, and contains no account IDs, routes or secrets. Authenticated runtime requests are held before backend access while the start gate is false; scoped model listing remains available. The durable_object scheduling policy does not support max_instances in the current CLI; fixed identity is a routing invariant, not a cloud billing cap. Company target pins belong in the private operations checkout and must pass its account/domain guard before an approved deployment.

Checkpoint/restore management, independently encrypted backup and recoverable key custody are still required. The current management endpoint proves lifecycle health only. Do not enable runtime start or admit provider credentials until those requirements and concrete cloud resource/budget approval pass. Local component and Workers-runtime evidence does not close physical scoped-key streaming, recovery, durable job resume or fleet soak acceptance.

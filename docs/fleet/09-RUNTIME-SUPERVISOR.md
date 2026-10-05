# Runtime lifecycle component

`scripts/lib/runtime_supervisor.py` manages a foreground process group and a real SQLite database in an explicitly owned canonical directory. It does not provision a gateway or activate provider credentials.

The caller supplies an absolute runtime argv, storage encryption key, management secret and runtime port. The child receives the exact owned `DATA_DIR`, retained storage key, loopback `HOSTNAME` and explicit port; shell execution and ambient credential inheritance are disabled. Use a foreground server. Processes that deliberately detach into another session require container-level lifecycle containment and an init/subreaper.

The `ready` property is a component gate: live leader, valid SQLite and explicit admission. The caller must separately verify actual HTTP readiness, request authentication and provider behavior. OmniRoute 3.8.50 `/healthz` returns plain text `ok\n` with HTTP 200 for lifecycle readiness; it does not establish provider authentication. Its installed `dist/` tree requires the package dependencies, including `next`; copying `dist/` alone is insufficient.

Backup uses SQLite's online backup API, including committed WAL, with a deadline. Restore validates incoming bytes, preserves an exclusive consistent recovery snapshot, stops and reaps the entire owned process group, checkpoints old WAL, removes only owned regular sidecars, atomically replaces SQLite, fsyncs and restarts. A surviving or unobservable process group holds replacement. A transient permission-denied existence probe remains held until absence is verified; persistent denial prevents restore. Existing unrelated rollback files are preserved.

Private acceptance receipts verify actual OmniRoute startup and a controlled database-state restore/restart in an isolated host copy with zero provider connections. Unit coverage includes an actual orphan descendant, forced-stop failure, WAL consistency, ownership/path rejection and failed replacement. This evidence does not certify a production image, Cloudflare transport, company key scopes or streaming, provider-secret recovery, physical Mac restore, durable job resume or fleet capacity.

Run `python3 -m pytest tests/test_runtime_supervisor.py -q` for the component checks. Production management endpoints still need their own authenticated caller and encrypted, independently recoverable backup/key contract.

## Explicit first initialization

`scripts/lib/runtime_initializer.py` adds `InitializingSupervisor.initialize_fresh(authorized=True, timeout=60)` for an empty, canonical, owned private directory. It lets the supplied foreground runtime create its own database and schema; it does not pre-create an empty SQLite file or bypass migration guards. Existing state and attempted reinitialization are held. Readiness requires SQLite integrity, a real schema, live owned process and the verified `/healthz` HTTP200 `ok\n` contract before the deadline, with directory identity checked again before acknowledgment. Initialization does not enable inference admission.

Failures and interruptions stop the owned process group and retain created state for reviewed recovery. Public errors are generic. Ten fixture checks and actual OmniRoute3.8.50 initialization passed on the host and Linux/amd64 Node24.21.0 with Python3.11.2, networking disabled, read-only container root and owned temporary storage; actual runtime retained zero providers. Run `python3 -m pytest tests/test_runtime_initializer.py tests/test_runtime_supervisor.py -q`. The accepted deployment Dockerfile still does not include this initializer or a management service.

## Authenticated lifecycle readiness boundary

`scripts/lib/runtime_readiness_http.py` exposes `create_readiness_server` without starting a runtime or entering a server loop. A trusted caller supplies a bounded, independently verified lifecycle probe. Only the distinct management key may call exact GET `/healthz` or `/_management/ready`; backend and storage keys are denied. Queries, normalized paths, duplicate authorization or length fields, request bodies, unsupported methods and `Expect` are rejected before the probe. Errors suppress reflected parser details and logs; connections close after each response. Header/request bytes and concurrent connections are bounded, with socket timeouts.

The lifecycle response does not enable inference admission. Twenty-two actual HTTP checks passed on host and Linux Python3.11.2; integration with actual Node24 OmniRoute proved held-before-init, ready-after-init and held-after-stop, with zero providers and admission disabled. The deployment image and Worker do not yet invoke this boundary; transport authentication/port wiring, checkpoint/restore, stream cancellation and durable acknowledgments remain separate integration work. Run `python3 -m pytest tests/test_runtime_readiness_http.py -q`.

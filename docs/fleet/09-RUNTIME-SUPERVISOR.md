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

## Bounded on-disk checkpoint snapshot

`scripts/lib/runtime_snapshot.py` exports Linux-only `write_bounded_snapshot(supervisor, output_leaf, max_bytes=64MiB, timeout=10)`. It holds the supervisor lock, uses SQLite online backup with source logical-size and progress checks, and produces a0600 standalone snapshot without allocating a whole database byte buffer. The finalized artifact is capped at64MiB; a source-growth rejection may follow one small SQLite copy batch. Hashing is bounded to64KiB chunks. Output leaves must match `sg-snapshot-<32 lowercase hex>.sqlite`; existing artifacts are never replaced.

The destination is accessed through its held file descriptor and only that completed scratch database is normalized to standalone DELETE journal mode. The source database/WAL remain live and unchanged by the helper. Actual published identity and bytes, root identity and directory fsync are required before returning metadata. Disputed outputs and unknown temporary replacements/sidecars remain available for reconciliation without a success acknowledgment.

Fifteen Linux failure checks passed, plus an actual Node24 OmniRoute chain covering bounded snapshot, independently keyed authenticated encryption/decryption, original-row restore, later-row recovery snapshot and whole owned group exit, with zero providers and admission disabled. Run `python3 -m pytest tests/test_runtime_snapshot.py -q` on Linux. The portable legacy `Supervisor.backup()` and restore's recovery path still read whole snapshot bytes; management integration must use/enforce reviewed current-state bounds rather than assuming the256MiB incoming restore limit bounds those reads. Local fsync does not establish container-loss, journal, R2 or company/device acceptance.

The online backup uses the documented [SQLite backup semantics](https://www.sqlite.org/c3ref/backup_finish.html) and Python's [descriptor-relative stat API](https://docs.python.org/3.11/library/os.html#os.stat).

### Legacy byte-returning recovery bound

The byte-returning supervisor backup method now limits source logical size, backup progress and returned bytes to 64 MiB. Restore uses this method for its pre-replacement recovery copy, and holds before stopping the child or replacing storage when current state exceeds that quota. The existing 256 MiB incoming restore limit remains separate. A final deadline check rejects late acknowledgment after validation/read. Management integration must still use the Linux owned snapshot/file interfaces and verify authenticated transfer, journal reconciliation and remote acknowledgment.

Linux service execution must retain an init/reaper such as the image’s existing `tini` entrypoint. A direct Python PID1 test left a terminated orphan as a zombie and correctly held process-group shutdown; do not reinterpret that hold as verified absence. Test the complete service under its intended init boundary.

### Local checkpoint job records

`LocalJobJournal` binds a caller-supplied job ID to its request digest and distinguishes `prepared` from `artifact-verified`. Reconciliation rechecks owned artifact bytes; missing journal or changed state stays held. The Linux-only initial publication uses renameat2 RENAME_NOREPLACE with no fallback, preserving a single link and refusing an existing destination. See https://man7.org/linux/man-pages/man2/rename.2.html. Directory fsync completes the publication acknowledgment. Actual SIGKILL before publication stays held; after publication, verified local reconciliation resumes the same ID. This is not remote acknowledgment, container-loss durability or physical fleet resume. Advisory locking assumes cooperating writers; same-UID hostile mutation is detected where tested, not fully excluded.

### Authenticated management mutation boundary

`create_management_server` returns a nonstarted listener for exact POST checkpoint and restore metadata routes. Only the distinct management key authenticates. Request line and headers share a32KiB budget and absolute connection deadline; bodies are canonical-length JSON bounded2048bytes. Schema validation precedes callbacks. `OperationGate` holds mutations when inference tokens are active and prevents new tokens during mutation; callers must integrate tokens around the actual complete upstream stream lifetime. Callbacks remain trusted bounded operations. Linux proof uses actual OmniRoute, owned encrypted files and local journal through HTTP; these proof callbacks are not a packaged deployment service. Provider credentials, remote acknowledgment and real SSE forwarding remain separate acceptance gates.

### Operation identity binding

`runtime_operation_identity` computes canonical request digests bound to operation kind, trusted instance/runtime/image/key-ID context, and operation fields. Restore has its own job ID and mandatory source-checkpoint job/digest plus encrypted artifact identity. Checkpoint digests cannot authorize restore. These pure validators must run before coordinator effects; the current generic management listener still validates its earlier metadata schema and does not yet invoke them. Restore intent and ambiguous-interruption holds must be integrated before service acceptance.

# Runtime lifecycle component

`scripts/lib/runtime_supervisor.py` manages a foreground process group and a real SQLite database in an explicitly owned canonical directory. It does not provision a gateway or activate provider credentials.

The caller supplies an absolute runtime argv, storage encryption key, management secret and runtime port. The child receives the exact owned `DATA_DIR`, retained storage key, loopback `HOSTNAME` and explicit port; shell execution and ambient credential inheritance are disabled. Use a foreground server. Processes that deliberately detach into another session require container-level lifecycle containment and an init/subreaper.

The `ready` property is a component gate: live leader, valid SQLite and explicit admission. The caller must separately verify actual HTTP readiness, request authentication and provider behavior. OmniRoute 3.8.50 `/healthz` returns plain text `ok\n` with HTTP 200 for lifecycle readiness; it does not establish provider authentication. Its installed `dist/` tree requires the package dependencies, including `next`; copying `dist/` alone is insufficient.

Backup uses SQLite's online backup API, including committed WAL, with a deadline. Restore validates incoming bytes, preserves an exclusive consistent recovery snapshot, stops and reaps the entire owned process group, checkpoints old WAL, removes only owned regular sidecars, atomically replaces SQLite, fsyncs and restarts. A surviving or unobservable process group holds replacement. A transient permission-denied existence probe remains held until absence is verified; persistent denial prevents restore. Existing unrelated rollback files are preserved.

Private acceptance receipts verify actual OmniRoute startup and a controlled database-state restore/restart in an isolated host copy with zero provider connections. Unit coverage includes an actual orphan descendant, forced-stop failure, WAL consistency, ownership/path rejection and failed replacement. This evidence does not certify a production image, Cloudflare transport, company key scopes or streaming, provider-secret recovery, physical Mac restore, durable job resume or fleet capacity.

Run `python3 -m pytest tests/test_runtime_supervisor.py -q` for the component checks. Production management endpoints still need their own authenticated caller and encrypted, independently recoverable backup/key contract.

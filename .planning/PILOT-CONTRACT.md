# Local mini pilot implementation contract

Python 3.10+, standard library only. No network, subprocess tool execution, global
packages, tenants, providers, or launchd configuration. External workers operate
in isolated output directories, with only their assigned files integrated.

Plan schema `snowgloves.node-plan.v1`: exact fields `schema`, `node`, `profile`,
`root`, `source_digest`, `steps`, `held`, `digest`. Profile is `local-pilot`.
Root is an absolute path. Node is `[a-z][a-z0-9-]{0,62}`. Source digest is SHA256.
Steps are exactly three ordered entries with fields `id`, `path`, `content`,
`depends_on`: `identity` -> `node.json`, `runtime` -> `runtime.json`, `operations`
-> `OPERATIONS.md`. All paths are beneath `<root>/.snowgloves-local/`.
Content is UTF-8 strings. No arbitrary commands or user-supplied executable paths.
Dependencies are [] then [identity] then [runtime]. Held is a list of reason
strings for live identity, vault, services, network, providers, physical acceptance.
Digest is SHA256 of canonical JSON of all fields other than digest (sorted keys,
compact separators, ensure_ascii=True, allow_nan=False).

`node_journal.py` API:
- `digest_plan(plan) -> str` computes canonical digest excluding digest.
- `apply(plan, reviewed_digest, *, resume=False) -> dict`
- `rollback(plan, reviewed_digest) -> dict`
- `status(root) -> dict` (read-only)
- `BootstrapError(message, code=1)` exposes `.code`; invalid data 3, drift/held/lock 2.

Mutation validates closed plan schema and exact steps, root confinement, digest,
and caller source freshness (CLI compares source_digest before mutation). Journal
is `<root>/.snowgloves-local/journal.json`; lock is `.lock`. Exclusive lock with
fcntl.flock prevents concurrent mutation and releases on process exit. Refuse
symlinks anywhere in the state tree. Atomic private writes fsync + replace.
Checkpoint each stage before its file write (`pending`) then after (`complete`).
Resume reconciles a pending stage if absent or exactly desired bytes, denies any
other bytes. New files owned=true; pre-existing identical files owned=false and
never removed on rollback. Pre-existing different files cause drift. Validate
journal schema and plan binding, never trust journal paths or ownership without
checks. Rollback preserves journal for evidence. Drift yields manual-recovery.
Local success state is configured, profile_ready=false; held requirements remain.

`node_bootstrap.py` API/CLI:
- `source_digest()` hashes VERSION + bootstrap/journal source contents, deterministic.
- `inspect(root) -> dict`: platform, machine, disk, tool presence via shutil.which;
  present paths are inventory evidence only. Root must exist. No subprocess.
- `make_plan(root, node) -> dict`: deterministic plan contract above.
- `main(argv=None) -> int` prints a JSON object on stdout, errors on stderr, no tracebacks.
- commands: inspect --root; plan --root --node; doctor --root; status --root;
  apply/resume/rollback --plan FILE --digest DIGEST; debug collect --root.
- doctor: typed findings with check id, status, reason, observed time, evidence
  digest, remediation. Missing mandatory local files fail=1; present local config
  plus live unknowns held=2; never call a port service identity. No paid probes.
- debug prints redacted allowlisted inventory, stage status, digest refs, findings.
  No env dumps, arbitrary captures, secrets, content strings, or raw errors.
- default root cwd; plan root uses absolute normalized path. argparse bad flags=3.

`bin/snowgloves`: shell launcher execs Python for `snowgloves node ...`; --version
and --help supported; delegates to scripts/node_bootstrap.py.

`scripts/install-local.sh --prefix PATH [--dry-run]`: source-root autodiscovery;
checks python >=3.10; new prefix only, same exact installed copy idempotent;
copies bin/snowgloves, scripts/node_bootstrap.py, scripts/node_journal.py, VERSION,
docs/LOCAL-MINI-PILOT.md and SHA256SUMS from verified package into private prefix.
No package installation, pip, services, sudo, profile changes, or symlink targets.

`scripts/package_pilot.py --output DIRECTORY`: bundle exactly those six files,
plus install-local.sh; create checksum manifest and tar.gz atomically. Verify
contents with --verify DIRECTORY; reject missing/extra files and symlinks.
No git commit/tag/push, no personal tenant files, no environment files.

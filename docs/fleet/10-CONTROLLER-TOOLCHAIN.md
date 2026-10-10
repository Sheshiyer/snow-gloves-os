# Controller toolchain foundation

The controller bootstrap plan requires pinned tooling and supported runtimes.
`scripts/fleet/toolchain.py` verifies an operator-reviewed, checksum-bound release
without installing packages or rewriting native configuration. Default inspection
hashes selected entry files. Explicit `--probe` executes only bounded `--version`
commands with a reduced environment; it never retrieves credentials or starts a
model job. npm uses the pinned Node executable, and that Node's directory leads
the version-probe PATH. Native runtime authentication remains a separate gate.

```sh
python3 scripts/fleet/toolchain.py \
  --release /private/controller-development-release.json \
  --release-digest REVIEWED_SHA256 --probe
```

The closed `snowgloves.toolchain-release.v1` JSON contract has exactly `schema`,
`node`, `system`, `machine`, `tools`. Each tool has exactly `id`, canonical absolute
`path`, entry-file `sha256`, and exact `version`. Supported IDs are brew, git, gh,
node, npm, python3, uv, codex and claude. npm requires a pinned Node. Duplicate
keys, unknown fields/tools, symlink paths, changed bytes, mismatched host/version,
nonregular or oversized files, timeouts and oversized process output fail closed.
An entry hash is not a complete distribution or supply-chain attestation.

Exit0 means all selected byte/version checks pass. Exit2 means held or unprobed;
exit3 invalid inputs/invocation. Raw tool output and ambient credentials are not
included in the result. Default inspection does not execute tools. Explicit
probes run the reviewed programs and are not an OS sandbox or a guarantee about
all behavior of those programs.

## Package-manager adapter plans

Supply an exact checksum-bound `snowgloves.toolchain-request.v1` JSON object with
`schema` and a `steps` list, plus an existing operator-owned planning root:

```sh
python3 scripts/fleet/toolchain.py \
  --release /private/controller-development-release.json \
  --release-digest REVIEWED_RELEASE_SHA256 \
  --request /private/tooling-request.json --request-digest REVIEWED_REQUEST_SHA256 \
  --root /private/owned-stages
```

| Adapter | Exact fields | Bound behavior |
|---|---|---|
| `uv-venv` | `adapter`, `target` | Pinned uv/interpreter; offline; config/project discovery and Python downloads disabled |
| `npm-ci` | `adapter`, `target`, `package`, `lock`, `network` | Pinned Node/npm; exact package/lock bytes; registry.npmjs.org tarball dependencies with full SHA512 integrity; scripts/audit/funding disabled; explicit network choice |
| `homebrew-bottle` | `adapter`, `artifact`, `dependencies` | Local checksum-bound bottle and explicit pinned dependency IDs; post-install steps skipped; shared prefix and full formula/dependency identity held for review |

`package`, `lock`, `artifact` are `{path, sha256}` records. Owned target names are
single normalized slugs, unique and absent. npm rejects linked/workspace sources,
Git/foreign-registry dependencies and incomplete integrity values. Plans bind the
release digest, canonical request, planner source bytes, root, argv and source
records. Source drift changes the plan; no mutable `latest` selector is used.

**These adapters currently produce review plans only.** There is no `apply`
command, and each step is explicitly non-executable. Staged application, manager
precondition rechecks, cancellation/journaling, failure reconciliation, full
dependency/source identity and fresh-machine verification remain T05 work.
Homebrew's unsupported `--ignore-dependencies` option is deliberately excluded;
the plan does not claim that Homebrew dependencies are confined or offline.
No automatic shared-prefix uninstall is a rollback.

## Coding01 development baseline

Physical baseline pins nine installed entries. The existing Node22.23.3 and
paired npm10.9.9 are selected for controller development; the currently running
services' Node26 configuration is preserved. Node22 is an LTS branch; Node26 is
currently a Current release according to the [official release schedule](https://nodejs.org/en/about/previous-releases).
This dated selection needs its own project build and future service compatibility
evidence; it does not certify every runtime or device. The [uv CLI](https://docs.astral.sh/uv/reference/cli/),
[npm ci contract](https://docs.npmjs.com/cli/v11/commands/npm-ci/) and [Homebrew install contract](https://docs.brew.sh/Manpage)
support the planned flags.

Fresh frontend setup excludes dependency directories. Remove the inherited
tracked `apps/infra-block/node_modules` symlink; `.gitignore` keeps future local
dependencies out of Git. A fresh setup must install from the reviewed lockfile,
rather than resolve another checkout's directory. PR47 tracks the same cleanup.

The original T01–T13 onboarding and fleet, issuer/RBAC, vault, service, recovery
and capacity requirements remain open at their recorded evidence levels.

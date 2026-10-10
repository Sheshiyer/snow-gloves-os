# Reviewed headless startup migration

`scripts/fleet/headless.py` packages an existing reviewed Coding Mac installation
as system LaunchDaemons. It does not provision credentials, configure Tailscale,
change FileVault, enable automatic login or install GUI applications. Grok Bot
is a client and must never be a startup dependency. The authoring Mac is excluded.

Source tests establish the migration contract. A successful `apply` establishes
installed launchd definitions only. `status` always returns
`cold_boot_verified: false`; physical reboot and power-restoration evidence must
be recorded separately in the private operations checkout and ISA.

## Preconditions and review contract

- Coding 01 uses `axio`; Coding 02 uses `maccoding2`, with the existing non-root
  UID/GID and `/Users/<user>` home. No root application process is generated.
- Source plists must be regular mode `0600` files in that user's
  `Library/LaunchAgents`; stdout/stderr must point inside existing user-owned
  private directories. Config and credential-file arguments must be private.
  Review and correct ownership/modes independently before planning; the tool
  never fixes permissions on unrelated files.
- Supply only exact labels that were installed and reviewed. There is no wildcard
  discovery or automatic selection. The allowlist includes the pilot coordinator,
  bridge, worker, UI, projection API, private TLS proxy, scheduled TLS renewal,
  HTTP MCP sidecar, `com.snowgloves.hermes` event bus and Coding 01 OmniRoute.
  Coding 02 permits only `fr.heyzack.snowgloves.coding02-worker` and
  `fr.heyzack.snowgloves.coding02-transport`. Pulse and GUI services are excluded.
- Source argv/environment are preserved except explicit service `HOME`, `USER`,
  `LOGNAME`, default absolute `PATH`, resolved Homebrew executable, private umask,
  background process type and a 30–300 second restart throttle. Schedules and
  their `RunAtLoad`/`KeepAlive` behavior are preserved. Inline shell commands,
  login shells, GUI/Keychain dependencies, unknown launchd properties and inline
  secret variables/arguments are refused rather than copied into a review plan.
- A reviewed absolute wrapper may read a protected credential file directly.
  It must not rely on a desktop Keychain, shell profile, SSH agent, desktop app,
  developer Vite server or implicit provider fallback. Its own interpreter and
  child commands also need absolute paths. The tool's conservative static scan
  is a guard, not a proof of wrapper behavior; inspect wrapper dependencies.
- Pass every runtime config and imported authority module that is not already an
  explicit file argument with repeated `--critical-file`. The plan fingerprints
  source plists, executable files, explicit file arguments and those extra files.
  It records hashes/ownership/modes, not configuration or credential contents.
  It cannot infer an entire dependency tree from arbitrary wrappers.
- The coordinator DB must have no `queued`, `running` or `cancel_requested`
  tasks. Reconcile uncertain worker executions/recovery holds first. Suspend new
  human/client submissions for the maintenance window. Coding 01 selection must
  include its coordinator, which is stopped before other service changes. Plan
  and apply bind to the same logical task-state digest; a changed DB, source,
  config, UID, host or launchd domain aborts the migration.
- A real operator root session is required for `apply`/`rollback`. Do not install
  a broad passwordless-sudo rule. If `sudo -n` is unavailable, stage and review
  the package and use the machine's authorized administrator interactively.

## Prepare a Coding 01 plan

Run from the reviewed installed source checkout as `axio`. First discover the
actual coordinator DB from the existing plist/config without printing tokens:

```sh
TASK_DB=$(/usr/bin/python3 - <<'PY'
import json, pathlib, plistlib
p=pathlib.Path.home()/'Library/LaunchAgents/com.snowgloves.hermes-pilot.coordinator.plist'
a=plistlib.loads(p.read_bytes())['ProgramArguments']
c=json.loads(pathlib.Path(a[a.index('--config')+1]).read_text())
print(pathlib.Path(c['data_root'])/'fleet.sqlite3')
PY
)
mkdir -m 700 "$HOME/headless-review"
```

Inspect is read-only and prints only labels, a digest and FileVault state. Plan
writes a new private JSON file and refuses overwriting an existing plan. Use
only installed labels from this explicit example; prepare missing production UI
or MCP sidecar definitions separately before including them:

```sh
python3 -B scripts/fleet/headless.py inspect --user axio \
  --quiescence-db "$TASK_DB" \
  --service com.snowgloves.hermes-pilot.coordinator \
  --service com.snowgloves.hermes-pilot.bridge \
  --service com.snowgloves.hermes-pilot.worker \
  --service com.snowgloves.hermes-pilot.ui \
  --service com.snowgloves.hermes-pilot.api \
  --service com.snowgloves.hermes-pilot.tls \
  --service com.snowgloves.hermes-pilot.tls-renew \
  --service com.snowgloves.hermes-pilot.mcp-http \
  --service com.snowgloves.hermes \
  --service com.temperance.engine.omniroute
```

Repeat that exact command with `plan` in place of `inspect`, adding
`--output "$HOME/headless-review/coding01.json"` and the reviewed
`--critical-file /absolute/private/runtime-config` arguments. JSON review must
confirm the selected services, non-root user, argv, environment, loopback/private
binds, logs, schedules and DB path. Review in place with
`python3 -m json.tool "$HOME/headless-review/coding01.json"`; never paste private
plans, raw launchctl output or configs into shared task logs. Record the printed
SHA-256 independently; it binds the exact reviewed plan and is not a signature.

## Coding 02 maintenance probe contract

The existing transport key is restricted to forwarding and must stay restricted.
It cannot run this read-only probe. Provision a **separate maintenance-only key**
under an explicit reviewed account change, or leave Coding 02 migration pending.
Do not copy founder keys or grant a shell to the transport identity.

The maintenance key on Coding 01 should have `restrict`,
`from="100.124.172.109"`, and a fixed `command` equivalent to:

```sh
/absolute/reviewed/python3 /absolute/reviewed/snow-gloves-os/scripts/fleet/headless.py \
  probe --quiescence-db /absolute/reviewed/private/data-root/fleet.sqlite3
```

Pin those absolute paths at provisioning; no caller-selected path or command
may reach the forced command. `probe` runs as `axio`, opens SQLite read-only,
checks integrity and emits exactly `{ok,pending,state_sha256,scheduler_loaded}`.
It emits no task IDs, titles, prompts, tokens or config content. A pending task
or invalid database returns a refusal and nonzero exit. `scheduler_loaded`
checks `com.snowgloves.hermes-pilot.coordinator` in system, GUI and user domains.
The caller sends an equivalent inline read-only probe; an SSH forced command
must ignore that request and run the pinned command above.

The separate Coding 02 private identity must be owned by `maccoding2`, mode
`0600`, usable without an interactive agent, and host keys must already be
verified/pinned. Client flags are `BatchMode=yes`, `StrictHostKeyChecking=yes`,
`ForwardAgent=no`, `IdentityAgent=none`, `IdentitiesOnly=yes` and explicit `-i`.
Root applies drop to `maccoding2` for the SSH probe. No credential is fetched,
bundled, copied into a plist or printed by this package.

On Coding 02, set `TASK_DB` to the exact Coding 01 DB path verified above, then:

```sh
mkdir -m 700 "$HOME/headless-review"
python3 -B scripts/fleet/headless.py plan --user maccoding2 \
  --quiescence-db "$TASK_DB" \
  --quiescence-ssh-host axio@coding-mac.tail32e298.ts.net \
  --quiescence-identity-file "$HOME/.ssh/snowgloves-maintenance" \
  --service fr.heyzack.snowgloves.coding02-worker \
  --service fr.heyzack.snowgloves.coding02-transport \
  --output "$HOME/headless-review/coding02.json"
```

## Apply, verify and roll back

Apply Coding 01 first during an empty maintenance window. Keep the recorded
digest literal in the root command; do not dynamically trust a hash read from an
unreviewed edited file. Use the same reviewed Python/source revision throughout.

```sh
sudo /absolute/reviewed/python3 /absolute/reviewed/snow-gloves-os/scripts/fleet/headless.py \
  apply --plan /Users/axio/headless-review/coding01.json \
  --expect-sha256 RECORDED_64_CHARACTER_CODING01_DIGEST
```

The helper serializes mutations with a root-owned lock, revalidates the plan,
and writes original selected plist bytes, plan provenance, a SQLite online
backup and a write-ahead journal under
`/private/var/db/snowgloves-headless/<plan-digest>/` before stopping anything.
It disables/stops selected user-domain services, removes their startup plists,
rechecks the task DB, then installs root-owned mode `0644` system plists and
bootstraps only the system domain. Original source definitions remain in the
mode `0700` root backup. A failure stops the procedure and leaves a
`rollback-required` journal; do not blindly retry.

The reviewed Coding Macs support `launchctl bootout --wait`; service stops use
that option with a 25-second command timeout before checking registration.
Disable-state inspection accepts both `true`/`false` and the
`enabled`/`disabled` words observed on these devices. A failed apply records the
fixed operation name, allowlisted service label and exception type, without
copying command output or credentials into the journal or operator response.

For Coding 02, keep new submissions suspended and temporarily stop Coding 01's
new coordinator so the remote probe can prove the scheduler is fenced:

```sh
sudo /bin/launchctl bootout system/com.snowgloves.hermes-pilot.coordinator
```

Apply Coding 02's own reviewed plan/digest as its administrator. Its backup is
local to Coding 02; the authoritative DB backup stays on Coding 01. Its two SQL
checks require the coordinator still stopped and the reviewed DB digest intact.
Then restart only Coding 01's owned coordinator definition:

```sh
sudo /bin/launchctl bootstrap system \
  /Library/LaunchDaemons/com.snowgloves.hermes-pilot.coordinator.plist
```

Run this status pattern on each machine with its own plan/digest:

```sh
python3 -B scripts/fleet/headless.py status \
  --plan "$HOME/headless-review/coding01.json" \
  --expect-sha256 RECORDED_64_CHARACTER_CODING01_DIGEST
```

`startup_candidate` requires FileVault confirmed **Off**, matching system
definitions, loaded system jobs and no selected user-domain duplicates. It does
not claim healthy endpoints, inference credentials, an active worker PID,
completed task execution or physical-boot acceptance. Scheduled renewals may
be loaded but intentionally idle. Test authenticated UI/API/gateway, transport
reconnect, event bus and a fresh coordinator→Coding 02→verified-artifact job.

Coding 02 FileVault disabling remains an operator action outside this package.
Verify `fdesetup status` reports Off after decryption finishes before unattended
cold-boot acceptance. Leave the authoring Mac's FileVault and inference alone.
Never enable automatic desktop login. Record lock-screen, SSH-disconnect,
monitor-disconnect, restart-before-login and controlled power-restoration tests
as distinct receipts, including a fresh authenticated job after each boot.

Rollback uses the original reviewed plan and digest:

```sh
sudo /absolute/reviewed/python3 /absolute/reviewed/snow-gloves-os/scripts/fleet/headless.py \
  rollback --plan /Users/axio/headless-review/coding01.json \
  --expect-sha256 RECORDED_64_CHARACTER_CODING01_DIGEST
```

Keep the fleet quiescent for rollback; Coding 02 also needs the Coding 01
coordinator stopped. All backup hashes and current selected destination/source
bytes are checked first. A newer operator edit or symlink aborts automatic
rollback. The coordinator stops before other system services are removed.
Original user plists/ownership/modes and prior enabled/loaded domains are restored.
If the original GUI domain no longer exists, definitions remain recoverable on
disk and a bootstrap refusal requires session-aware operator reconciliation.
Unrelated services are untouched. The database backup is **never** automatically
restored over newer task history; test restore against an isolated private path.

## Dependency-free verification

```sh
python3 -B -m unittest discover -s tests -p test_fleet_headless.py -v
```

Tests simulate launchctl and root-only locations inside a temporary directory.
They cover backup-before-stop, non-root generation, failure journaling, full
rollback, digest/account/host/domain tampering, source/config drift, newer
operator changes, GUI/Keychain/inline-secret exclusion, private path bounds,
scheduled renewal, fixed remote probes, quiescence and FileVault reporting.
They perform no live service changes, SSH, sudo or disk-security actions.

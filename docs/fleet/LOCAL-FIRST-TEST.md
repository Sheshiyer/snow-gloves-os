# Local first test and one-device-at-a-time rollout

Use Python **3.11+**, Node 20.19+/22.12+ or a newer supported major, and the reviewed platform source. Start with Mac Coding 01 and HeyZack. The current test proves local configuration generation and the private loopback workspace. It does not install upstream skills, authenticate MCP servers or prove an LLM job, reboot, restore or fleet capacity.

## Bind the device without renaming macOS

Record `system_profiler SPHardwareDataType -json` through an allowlist containing model name, model identifier, chip and memory. Do not store serial numbers or hardware UUIDs. Record architecture, macOS, free disk and CLI versions. Read `scutil --get LocalHostName` locally for the inventory binding; ComputerName may contain spaces and is not the DNS-safe identifier required by the fleet projection.

In the private checkout, review existing assignments and back up `fleet.yaml` before editing. Add the selected canonical slot under `islands`, with exactly `wing` and `hostname`. Create its own matching `nodes/islands/<slot>/node.yaml` from the reviewed wing policy, using this device's actual hostname and operator account. Preserve existing assignments and reject duplicate hostnames across slots. Do not copy another machine's credentials or assert health from this registration.

| Order | Canonical slot | Wing policy | Distinct acceptance |
|---|---|---|---|
| 1 | `mac-coding-1` | `coding` | Current local reference |
| 2 | `mac-coding-2` | `coding` | Fresh identity, configuration, runtime and artifact |
| 3 | `mac-creative` | `design` | Reviewed creative module intersection and artifact |
| 4 | `mac-marketing` | `marketing` | Reviewed marketing choices, connector scope and local draft |

The slot-specific profile currently binds the world projection; `node_profile.py` and `doctor.py` still use the shared wing profile. The doctor's `--wing coding` flag is an inspection override and does not prove which coding device is running. Record exact slot identity separately.

## Prepare only workspace dependencies

Transfer the verified public bundle and the authorized private checkout separately. On a fresh target, after bundle verification:

```sh
python3 VERIFY.py check
python3 -m venv .venv
.venv/bin/python -m pip install PyYAML==6.0.3
npm --prefix apps/infra-block ci
export SNOWGLOVES_DATA=/absolute/path/to/snow-gloves-ops
.venv/bin/python -B scripts/onboard.py --prompt codex
.venv/bin/python -B scripts/ops_workspace.py check --data-root "$SNOWGLOVES_DATA"
```

The bundle includes a prebuilt town. `npm ci` installs workspace dependencies from its lockfile. The onboarding interview reads the packaged prompt. Private profiles and tenants stay outside the public bundle. Hermes configuration and graph-walk fixtures are not included; this kit does not install or start Hermes, gateways or native agent runtimes.

## Review and run the adapter canary

Choose a **new**, private review directory for every device/run. The render output is inspectable configuration, not installed plugins or fetched upstream code. The three coding pointers produce references only; GitHub MCP needs its reviewed binary and auth, and Playwright MCP still needs a reviewed version pin. Stop before a native runtime write until its permanent path/runtime decision is recorded.

```sh
export SG_CANARY_ROOT="$SNOWGLOVES_DATA/.planning/coding01-new-local-test"
.venv/bin/python -B scripts/fleet/node_profile.py --data "$SNOWGLOVES_DATA"   render --tenant heyzack --node coding --runtime codex --out "$SG_CANARY_ROOT"
```

Read the dry-run file list and unresolved adapter fields. It should report five effective coding modules, three pointer skips and zero selected tenant agents for the inspected HeyZack selection. Confirm the output directory does not yet exist. Run the same command with `--write` to create files exclusively inside the review directory. Read `tenant/runtime/coding/codex/render.json`, then repeat the write and compare relative file lists and SHA-256 hashes. Identical output proves this render's repeatability; it does not establish the unimplemented installer's idempotent apply/resume/rollback criteria.

A completion receipt must carry a unique job ID, canonical `nodeId`, tenant, role/agent attribution, actual command, source revision, start/end time, exit code, output file hashes and artifact hash. Use `kind: local-adapter-canary` and explicitly record `modelExecuted: false`, `connectorsInvoked: false`. Verify the artifact by reading its bytes before appending a completed job/artifact to that tenant's private `audit/jobs.jsonl` and `audit/artifacts.jsonl`. An agent field here attributes the role; it does not assert that an enabled model agent executed. Do not emit a running record after the process has already completed.

## Open and verify the actual town

Check that both ports are free; identify any existing listener rather than replacing it. The launcher refuses occupied ports:

```sh
.venv/bin/python -B scripts/ops_workspace.py run --data-root "$SNOWGLOVES_DATA"
```

Open `http://127.0.0.1:18760/` in the Codex in-app browser. Verify Mac Coding 01 is Configured while Coding 02 remains Planned until independently enrolled. Open Field Kit, select HeyZack, choose Courier trail → Jobs and inspect the completion envelope. Its `nodeId` must be the exact current canonical slot. Switch to a second tenant and confirm the first tenant's job is absent. Completed work should not leave every character walking.

Stop only this owned foreground launcher with Ctrl-C. Verify both child listeners disappear, then restart and recheck the source projection. These foreground children do not persist across reboot. Read-only endpoint observations, even a healthy gateway HTTP response, do not establish provider credentials or authenticated streaming.

## Runtime and promotion gates

After host pressure admission succeeds, run one bounded task through the selected existing runtime/rail, record the resolved provider/model from correlated evidence and verify the actual output. Keep this separate from connector authentication. A prelaunch exit125 `host_pressure_elevated` means no model request ran; retain that receipt and retry after admission returns normal. Do not disable the guard or terminate unrelated work to force a pass.

Before promoting Coding 01 to operational, resolve its permanent runtime/agent selection, upstream dependency pins, connector auth, owned startup, interruption/resume, backup restore and capacity requirements. The historical bootstrap lifecycle CLI remains a draft. Repeat the same evidence gates for each later Mac using its own slot and credentials. Update the private [100-point checklist](ONBOARDING-100.md) instance and ISA with fresh evidence, never by copying the prior device's checkmarks.

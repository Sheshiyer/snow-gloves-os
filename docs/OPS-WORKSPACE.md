# Mac mini operations workspace

This path opens the existing Snow Gloves Field Kit against an explicitly selected
private operations checkout. It uses the current platform API and frontend. It
does not enroll a device or activate agent runtimes, providers, or connectors.

Keep `snow-gloves-os` and the private `snow-gloves-ops` checkout beside each
other, outside iCloud-synchronized folders. Transfer or clone each through its
authorized repository access. Never publish the private checkout or copy tenant
records into the platform's static frontend assets.

## Prepare the workspace

From the platform checkout, use an isolated Python environment and the checked-in
frontend lockfile:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-ci.txt
npm --prefix apps/infra-block ci
npm --prefix apps/infra-block run build
```

Python must support the platform's Python 3.10+ source. Node must satisfy the
locked frontend packages' engine requirements; check installation warnings before
continuing. These commands install workspace dependencies, not global agent CLIs.

Set the private instance location in the terminal used for existing onboarding
and fleet commands:

```sh
export SNOWGLOVES_DATA="$(cd ../snow-gloves-ops && pwd)"
```

The cockpit deliberately ignores this environment variable. Its private root
must also be passed explicitly.

## Inspect without starting services

The current snapshot command reads source and private instance metadata without
probing local endpoints:

```sh
.venv/bin/python scripts/infra_cockpit.py \
  --data-root "$SNOWGLOVES_DATA" --tenant heyzack --snapshot --no-probe
```

The result is private operator metadata. Do not save it in `apps/infra-block/public`
or commit it to the platform repository. Omit `--tenant heyzack` to inspect all
available tenant metadata; private activity requires a selected tenant.

## Open the UI

First check whether either workspace port is already occupied:

```sh
lsof -nP -iTCP:18760 -sTCP:LISTEN
lsof -nP -iTCP:18761 -sTCP:LISTEN
```

An existing listener needs identification. Do not kill or replace a shared
process. In a free workspace, start the API in one terminal:

```sh
.venv/bin/python scripts/infra_cockpit.py \
  --data-root "$SNOWGLOVES_DATA" --no-probe
```

In another terminal, start the built UI:

```sh
npm --prefix apps/infra-block run preview
```

Open <http://127.0.0.1:18760/> on that Mac mini. The preview proxies `/api/infra`
to the loopback API on port 18761. Open Field Kit, select the intended tenant,
and use Neighborhoods, Crew, Parts chest, Wing hangar, Blueprint bench and Stamp
book. To restrict the entire API to one tenant, add `--tenant heyzack` when
starting it. Stop each owned foreground process with Ctrl-C in its own terminal.

Both listeners stay on loopback. Remote browser access requires a separately
reviewed access method; this guide does not expose private operations to a LAN
or public host. These foreground processes do not persist across reboot.

## Use the existing onboarding tools

Review the current runtime choices and plan-mode interview prompt:

```sh
.venv/bin/python scripts/onboard.py --steps
.venv/bin/python scripts/onboard.py --prompt claude
```

For an already enabled tenant, review the wing-scoped adapter output:

```sh
.venv/bin/python scripts/fleet/node_profile.py \
  --data "$SNOWGLOVES_DATA" render \
  --tenant heyzack --node coding --runtime claude
```

This command renders a dry-run; review its destination and admitted module
intersection before choosing `--write`. A node allowlist does not enable tenant
modules. Do not enable every branch just to populate the UI.

The optional Textual onboarding UI uses `requirements-tui.txt` inside the same
virtual environment and `scripts/tui_onboard.py`. It handles onboarding; the
Field Kit handles source inspection and proposals. A reviewed harvest and adapter
write are separate from the read-only workspace startup.

## Acceptance boundaries

The current UI exposes catalog, tenant metadata, agent definitions, routing
previews and ledger evidence. Brand context text stays private. Registered
sources and ingestion plans do not establish embedded knowledge or completed
agent jobs. A copied research snapshot does not approve its claims or launch a
brand. A reachable endpoint does not prove authenticated provider behavior.

Verify the UI and CLI on the identified Mac mini before recording installed
device acceptance. Physical recovery, durable same-job handoff, authenticated
company gateway streaming and measured fleet capacity each retain their own
criteria in `ISA.md`.

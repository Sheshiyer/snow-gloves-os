# Infrastructure cockpit

The Infra Block city opens an operations workspace over the Snow Gloves platform.
The workspace uses a loopback projection API rather than reading host files from
the browser or connecting directly to the unscoped Hermes event endpoint.

## Run locally

In one terminal, from the repository root:

```sh
python3 scripts/infra_cockpit.py
```

In a second terminal:

```sh
npm --prefix apps/infra-block run dev
```

Open `http://127.0.0.1:18760/` and select **Operations**. The API listens on
`127.0.0.1:18761`; Vite proxies `/api/infra` through the frontend's own origin.
The production build can be used with `npm --prefix apps/infra-block run preview`
while the same local API is running.

## Data and authority

The default API reads public catalog and fixture data from this checkout. It
ignores ambient `SNOWGLOVES_DATA`. An explicit `--data-root` selects a private
instance checkout. Add `--tenant <slug>` to pin one tenant; private activity is
omitted when no tenant is selected. Instance records are projected through field
allowlists and bounded readers. Tenant context prose and credential values are
not part of the browser contract.

To inspect an instance explicitly:

```sh
python3 scripts/infra_cockpit.py --data-root /path/to/snow-gloves-ops
# Optionally pin a tenant, including requests from the browser:
python3 scripts/infra_cockpit.py --data-root /path/to/snow-gloves-ops --tenant <slug>
```

The eleven sections cover Overview, Agents, Modules, Runtimes, Connectors,
Tenants, Fleet, Activity, Workbench, Evidence and Resources. A landmark opens its
matching section. Global search finds modules, agents, adapters, connectors,
tenants, profiles, activity and indexed source documents. Runtime `verify` flags
mean fields still need confirmation; they do not prove an installation.

Inventory, source definitions, endpoint observations, ledger acceptance and
physical execution are distinct evidence. A reachable health endpoint is labeled
as an endpoint observation. A profile is not an enrolled device, and a missing
session API does not create synthetic sessions.

Fleet views expose sanitized node profiles. Private host/operator inventory is
not returned, and the snapshot reports that boundary explicitly. The session and
recovery panel links source contracts and the open acceptance ledger. It does not
offer session execution, container lifecycle or restore controls.

## Interfaces

| Route | Behavior |
| --- | --- |
| `GET /api/infra/snapshot?tenant=<slug>` | Versioned inventory and scoped metadata |
| `GET /api/infra/document?path=<indexed-path>` | Bounded public source text and content digest |
| `POST /api/infra/plan` | Pure routing and module-gate proposal |

The snapshot schema is `snowgloves.cockpit.v1`. The plan schema is
`snowgloves.cockpit.plan.v1`. Plans contain routes, per-module decisions, proposed
or held steps and reasons. Downloading a proposal creates a local JSON artifact;
it does not publish a Hermes event, enable a connector, approve a ticket, install
an adapter or run a provider. Execution, enablement and approval capabilities are
false in this API.

Only indexed public repository documents are readable. There is no arbitrary
file, artifact download, remote URL or shell-command endpoint. Host and Origin
checks, body limits and generic error responses protect the loopback boundary.

When the API is unavailable, the UI can display the bundled public-source
snapshot with an explicit disconnected/stale label. Private snapshots are not
stored as a browser fallback. The city and original game remain usable.

## Verification

Backend reader and HTTP tests cover scope, path isolation, gate previews and
read-only behavior. Client tests cover schemas, scope binding and transport
failures. Production compilation and IAB desktop/mobile flows verify the combined
application. The acceptance criteria and actual results live in `ISA.md`.

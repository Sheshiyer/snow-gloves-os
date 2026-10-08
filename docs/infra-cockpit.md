# Infrastructure Field Kit

The Infra Block city opens a Toy Town Field Kit over the Snow Gloves platform.
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

Open `http://127.0.0.1:18760/` and select **FIELD KIT**. The API listens on
`127.0.0.1:18761`; Vite proxies `/api/infra` through the frontend's own origin.
The production build can be used with `npm --prefix apps/infra-block run preview`
while the same local API is running.

## Residents and home encounters

The home projects seven source-backed agent identities as distinct procedural
characters and personal stations. Character and station clicks open the same
encounter as the keyboard-accessible portrait belt. Encounters link the actual
public `IDENTITY.md` and `SOUL.md` documents, focus the matching landmark and open
the matching agent workspace. Blueprint proposals remain available directly
from the home. Optional Map & source notes retain the sixteen-node source list,
filters, inspector and accessible map fallback.

`residents.ts` derives presence separately from scene motion. Only explicit,
nonfuture activity for the exact selected tenant and agent can be observed.
Active job/event evidence expires after 120 seconds; a newer terminal record for
the same job supersedes its older active record. Absent or stale activity is
unobserved, so residents remain at their stations without a claim of actual idle
runtime. Pending approval evidence produces a held stance. Health observations,
catalog entries and installed configuration cannot produce active presence.

The optional crew tour is a labeled local demonstration. It drives the scene
through a separate `demo` presence input and creates no synthetic snapshot or
job records. Stopping the tour returns to the current evidence projection.
Reduced-motion preference suppresses walking. The original demolition game
keeps its separate characters, scoring, pause and timer rules.

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

## Stations and materials

The horizontal toolbelt opens eleven stations. The kit uses a compact, nonmodal
right drawer on desktop and a bottom sheet capped at 60dvh on narrow screens.
Short landscape screens place the drawer in the right 48% and keep the town
and toolbelt on the left, with separate space for each.
The real miniature city remains visible and accepts pointer interaction. Station
selection focuses a corresponding source-backed city landmark; **Pack away**
closes the kit. The source and activity record viewers remain native modal dialogs.

| Visible station | Section / source | Local toy illustration and treatment |
| --- | --- | --- |
| Town square | Overview | Pink-roof house, teal robot companion, destination tokens and endpoint lantern tickets |
| Crew | Agents | Rounded plastic robot badges for actual agent roles, hooks and routed skills |
| Parts chest | Modules | Multicolored studded wooden blocks and collectible catalog cards |
| Platforms | Runtimes | Console cartridges for actual adapter formats, paths and verification gaps |
| Signal plugs | Connectors | Cream cables and coral plugs around capability gates |
| Neighborhoods | Tenants | Pastel houses and scoped neighborhood passports |
| Wing hangar | Fleet | Gold airship pieces for source or local wing profiles |
| Courier trail | Activity | Folded envelopes with wax seals and filtered record tickets |
| Blueprint bench | Workbench | Blue paper, pencil and a proposal form with actual gate decisions |
| Stamp book | Evidence | Wood-handled stamps and ledger tickets retaining open/accepted status |
| Field notes | Resources | Mint book covers and indexed source document records |

The illustrations are fixed local SVG artwork. Their material colors are
decorative; actual disposition, risk, reachability and acceptance values remain
explicit text. The town-square station counts come from the current snapshot.
Global search finds modules, agents, adapters, connectors, tenants, profiles,
activity and indexed source documents. Runtime `verify` flags mean fields still
need confirmation; they do not prove an installation.

**Connection notes** folds scope, connection source, update age and refresh into
an optional disclosure. The kit refreshes every fifteen seconds while open and
visible, and supports manual refresh. Technical addresses and observation times
are available in endpoint ticket disclosures rather than occupying the main
station heading. Activity and evidence use tickets rather than tables.

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
stored as a browser fallback. A failed selected-scope refresh clears projected
metadata, source and activity dialogs, pending proposals and related draft state;
late responses cannot restore the cleared projection. The city and original game remain usable.

## Verification

The home supports direct local exploration as any of the seven crew residents.
WASD/arrows walk relative to the camera, digits1–7 select a role, and E opens a
nearby station encounter. A compact edge HUD and close following camera keep the
town as the primary surface. Manual character movement is explicitly labeled
local exploration and never becomes job/activity evidence. Field Kit, encounter,
notes and typing interactions suspend movement; the original sandbox remains a
separate round with its existing pause behavior.

Backend reader and HTTP tests cover scope, path isolation, gate previews and
read-only behavior. Client tests cover schemas, scope binding and transport
failures. Production compilation and IAB desktop/mobile flows are the combined
application checks; a source or build check alone does not establish visual or
physical-device acceptance. The acceptance criteria and actual results live in `ISA.md`.

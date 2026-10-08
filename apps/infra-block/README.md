# Infra Block

A playable tabletop city maps sixteen infrastructure components to inspectable buildings. Seven role-specific residents inhabit the town, with personal work stations and clickable encounters. Explore their sources and tools or play a 45-second demolition round.

## Installation

Run these commands from `apps/infra-block`:

```bash
npm install
```

## Development

To start the development server:

```bash
npm run dev
```

## Build

To build the project:

```bash
npm run build
```

## Testing

To run tests:

```bash
npm test
```

## Configuration

The application runs on port 18760 by default.

## Gameplay Controls

- Movement: WASD or arrow keys
- Attack: Space
- Stomp: R
- Car grab/throw: E
- Pause: Escape
- Restart: Restart button
- Inspect buildings by clicking on them

## Gameplay Notes

- The gameplay simulation runs in the browser only.
- City inspectors describe public repository sources. The Field Kit uses a separate scoped API and bounded endpoint observations; building descriptions are not live device telemetry.
- No infrastructure mutation is performed. Field Kit reachability means an endpoint observation only, not a running job or enrolled device.
- Procedural geometry placeholders are used; no GLB assets are supplied.
- Physical and cloud acceptance are tracked separately in ISA.md. Coding doctor/job evidence is accepted; Marketing and Design remain open.

## Project Structure

- `data.ts`: Exports the InfraNode[] array with detailed node definitions.
- `contracts.ts`: Contains type definitions used across the project.
Repository sources referenced by inspectors live outside this app:

- `agents/`: Contains agent role identity files.
- `scripts/`: Contains operational scripts such as hermes.py, ingest.py, and others.
- `docs/`: Documentation including architecture, fleet, and adapters.
- `catalog/`: Module and options catalogs.
- `nodes/`: Node YAML files for marketing, design, and coding.
- `skills/`: Skill definitions such as connector-gate.

## Node Relationships

- `connector-gate` links to `hermes-bus` which links to `agent-chief-of-staff` and onward to agents.
- Knowledge flow: `knowledge-archive` → `agent-librarian` → `agent-interpreter` → `agent-dispatcher` → `agent-sentinel`.
- Tenant vault connects to `connector-gate`, `module-catalog`, `runtime-adapters`, and `knowledge-archive`.
- Fleet wings connect to `omniroute-gateway` which connects to `cloud-recovery`.

## Evidence and Sources

- All agent roles and nodes are documented with source files and scripts.
- Fleet wings and cloud recovery have pending or local candidate status as noted.
- Tenant instance data is private and not publicly exposed.

---

For further details, refer to the source files and documentation within the repository.

## Delivery verification

The city contains 16 public infrastructure entities and 31 verified repository source references. Its buildings represent the seven agent roles, Hermes bus, connector gate, knowledge archive, module catalog, runtime adapters, fleet wings, OmniRoute gateway, cloud recovery and tenant vault. Evidence badges describe source/local/pending acceptance rather than polling live systems.

- Strict TypeScript and Vite production build pass; 33 focused game and independent acceptance tests pass.
- Codex in-app browser checks cover desktop exploration, filters/search/walkthrough, characters, keyboard play, pause/retry and actual 45-second results.
- Narrow viewport and touch emulation checks cover the repaired canvas sizing, touch grab/throw/stomp, mobile dialog and reduced-motion preference. Physical phone testing has not been performed.
- Actual downloads verified: 1080×1350 PNG and a 1.24 MB VP9/WebM replay. Recording uses the first supported browser MIME; unsupported browsers expose an unavailable state.
- Challenge links preserve block, character and target score. The result panel exposes a readonly URL, clipboard feedback and native sharing when available. Scores are browser-computed.
- Use **2D MAP** or `?view=map` for the accessible data grid. It shares the rendering-failure fallback; deliberate map preference was browser tested, while actual WebGL startup failure was inspected in source. Sandbox requires the 3D view.
- Principal interface copy supports English and Simplified Chinese; repository names, source contracts and detailed infrastructure descriptions remain in English.

The prescribed GPT-5.4 audit was unavailable for this ChatGPT account and the advisor timed out. Neither supplies an audit pass. Controller tests and actual browser receipts support the delivered frontend.

Models are procedural toys. `asset-slots.json` records future GLB model slots; original animated GLBs were not supplied. No external model generation, analytics or infrastructure mutation is performed. Endpoint observations in the Field Kit remain distinct from live execution and physical-device proof.


## Toy Town Field Kit

Select **FIELD KIT**, or **Open workspace** in a building inspector, to open the
source-backed operational station for that part of the town. A horizontal belt
holds Town square, Crew, Parts chest, Platforms, Signal plugs, Neighborhoods,
Wing hangar, Courier trail, Blueprint bench, Stamp book and Field notes. These
retain the Overview, Agents, Modules, Runtimes, Connectors, Tenants, Fleet,
Activity, Workbench, Evidence and Resources contracts.

The nonmodal desktop drawer leaves the miniature town visible and interactive.
On narrow screens it becomes a bottom sheet capped at 60dvh, with the belt above
it. Short landscape screens instead use a right-hand drawer beside the town;
the belt has its own reserved space beneath the city. Local colored SVG toys
distinguish the stations: house and robot, studded
blocks, cartridges, plugs, pastel houses, airship, sealed envelope, blueprint,
wood stamp and mint book. Their colors describe materials; they do not replace
actual risk or disposition labels. Courier records and evidence criteria use
stamped tickets with their real source values.

Search is available above the drawer content. **Connection notes** discloses the
scope, connection source, freshness and manual refresh. The scoped snapshot
refreshes every fifteen seconds while the kit is open and visible. **Pack away**
returns to the city; Escape closes the kit when a source or activity modal is not
open. Opening the kit during gameplay preserves the paused timer.

The document viewer displays indexed source text safely, its content digest and
any truncation notice. The Blueprint bench generates a real backend routing and
module-gate proposal and downloads local JSON. It provides no execute, enable or
approve action. Failed scope loads clear old projections, dialogs and pending
proposals; disconnected public fixtures remain explicitly stale.

Run the loopback API from the repository root in another terminal:

```sh
python3 scripts/infra_cockpit.py
```

The frontend proxies `/api/infra` to `127.0.0.1:18761`. Explicit private instance
selection, exact API routes, evidence boundaries and station materials are
specified in [Infrastructure Field Kit](../../docs/infra-cockpit.md).
Current visual acceptance results belong in `ISA.md`; the earlier city delivery
receipts above do not by themselves verify this revised layout on physical
phones.

## Inhabited home

Meet the CEO, CTO, Chief of Staff, Librarian, Interpreter, Dispatcher and Sentinel
by selecting a character, a personal station or a portrait in the crew belt.
Each encounter shows the actual role, its identity and soul source files, the
current presence evidence, and actions to meet at the landmark or open the
matching agent Field Kit. The home also provides a Blueprint bench and optional
Map & source notes for the complete infrastructure list and original inspector.

Characters carry role-specific props: a compass, engineering tools, routing
board, books, interpretation lens, courier bag and audit shield. Their stations
use the same role metaphors. These visuals illustrate source roles; they do not
invent personal biographies or prove runtime activity.

Recent explicit job or event records can send a resident walking along town
roads only when the agent and selected tenant match. Active evidence expires
after two minutes. A newer terminal record for the same job suppresses the older
active record. Unknown or stale evidence parks residents at their stations with
an honest absence-of-evidence label. Endpoint health and configured adapters
never imply that an agent is working.

**Try crew tour** demonstrates the routes locally with a visible DEMO label.
**Stop tour** restores the actual projected presence. The tour creates no job,
event or approval records. Reduced motion suppresses nonessential walking.
The home refreshes its read-only snapshot while visible; the Field Kit owns
polling while open. Private failure clears the home projection, and public
offline fixtures remain explicitly disconnected and stale.

The inhabited-home verification adds 48 meaningful presence and renderer checks
to the original 53 frontend checks, for 101 passing tests. Renderer checks cover
all seven complete deterministic routes and building-footprint clearance.
Actual IAB checks cover character/station clicks, all seven keyboard encounters,
indexed source reading, exact agent workspaces, tour walking and parking,
portrait/landscape layouts, reduced motion, private-scope loss and successful
response scope downgrades. The phone layouts are browser emulation. Current
private all-scope activity is absent, so observed running jobs have not been
demonstrated in the live instance; the labeled tour supplies the visual preview.

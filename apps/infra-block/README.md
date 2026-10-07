# Infra Block

A playable tabletop city maps sixteen infrastructure components to inspectable buildings. Explore source relationships or play a 45-second demolition round.

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
- Infrastructure descriptions are projected from public repository sources; service status is not polled.
- No infrastructure mutation or live telemetry is performed.
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

Models are procedural toys. `asset-slots.json` records future GLB model slots; original animated GLBs were not supplied. No external model generation, analytics, live telemetry or infrastructure mutation is performed.

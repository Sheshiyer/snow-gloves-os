# Infra Block

A playable tabletop city maps sixteen infrastructure components to inspectable buildings. Explore source relationships or play a 45-second demolition round.

## Installation

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

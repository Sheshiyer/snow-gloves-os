# Snow Gloves OS — Mac Fleet & Axtech Operations

Updated 2026-09-30. This Project is the human roadmap; repository specs own implementation contracts. All new work is planning/backlog, with no live acceptance claimed.

## Delivery sequence

Foundation → runtime → distributed fleet → live visualization → brand capabilities → measured acceptance. Session World fixture prototyping can start before live orchestration.

| Key | Work package | Dependencies |
| --- | --- | --- |
| R00 | [Roadmap: Mac fleet, Axtech operations, and Session World](https://github.com/Sheshiyer/snow-gloves-os/issues/16) | None |
| R01 | [Bootstrap: fresh Mac inspection, release manifest, and tooling](https://github.com/Sheshiyer/snow-gloves-os/issues/17) | R00 |
| R02 | [Identity: verified organization, brand RBAC, and action approvals](https://github.com/Sheshiyer/snow-gloves-os/issues/18) | R00 |
| R03 | [Secrets: encrypted dotenv sync and scoped device enrollment](https://github.com/Sheshiyer/snow-gloves-os/issues/19) | R01,R02 |
| R04 | [Runtime: Temperance, OmniRoute, remote access, and supervised services](https://github.com/Sheshiyer/snow-gloves-os/issues/20) | R01,R02,R03 |
| R05 | [Doctor: evidence-based diagnostics, repair plans, and debug bundles](https://github.com/Sheshiyer/snow-gloves-os/issues/21) | R01,R02,R04 |
| R06 | [Fleet: control plane, node agents, durable jobs, and streaming](https://github.com/Sheshiyer/snow-gloves-os/issues/22) | R02,R04 |
| R07 | [Sessions: runtime adapters, isolated workspaces, and verified handoffs](https://github.com/Sheshiyer/snow-gloves-os/issues/23) | R03,R06 |
| R08 | [Operator tooling: Codex app/CLI, Claude, Grok, and Orca evaluation](https://github.com/Sheshiyer/snow-gloves-os/issues/24) | R01,R04 |
| R09 | [Session World: playable 3D pixel-art fleet cockpit](https://github.com/Sheshiyer/snow-gloves-os/issues/25) | R00; live telemetry R06; live controls R02,R07 |
| R10 | [Axtech: source-backed brand map and lead/campaign connectors](https://github.com/Sheshiyer/snow-gloves-os/issues/26) | R02,R03,R06 |
| R11 | [Media: paid generation, artifact pipeline, and brand budgets](https://github.com/Sheshiyer/snow-gloves-os/issues/27) | R02,R03,R06 |
| R12 | [Acceptance: recovery and 50-session multi-Mac fleet soak](https://github.com/Sheshiyer/snow-gloves-os/issues/28) | R05,R06,R07,R08,R09; campaign/media profiles R10,R11 |

## Existing acceptance

[Will-organ service gate #8](https://github.com/Sheshiyer/snow-gloves-os/issues/8) remains open and is preserved on this board.

## Evidence and authority

40–50 sessions across 4–5 Macs is a test target, not measured capacity. Separate durable sessions, executing jobs, and simultaneous provider calls. One-Mac tests use the same network protocol as multi-Mac execution. Roles, device trust, approvals, budgets, and secret access remain separate.

Orca is an evaluated workspace candidate; OpenOrca is an evaluated visualization candidate. Neither is approved as the org authorization backend. 3D Session World is a scoped synthetic nightly prototype before live controls.

Installation, authentication, source tests, live behavior, paid calls, deployment, and campaign sends require their own receipts. Do not mark Done based on installed binaries or a listening port. No fabricated dates or completion percentage.

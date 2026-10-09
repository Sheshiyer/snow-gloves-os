# Capability transition for the four-Mac fleet

This is the portable package map for Mac Coding 01, Mac Coding 02, Mac Creative and Mac Marketing. Mac Creative uses the existing `design` wing. A catalog entry, an installed host component and an authenticated connector are separate facts. The first onboarding target is HeyZack on Mac Coding 01; the other devices repeat the same process after its local proof is reviewed.

## What the source already supplies

The 9 October 2026 source catalog contains **135 cards**: 64 `add`, 45 `pointer`, 14 `hold` and 12 `refuse`. Categories are 79 skills, 36 playbooks, 13 plugins, 6 MCP cards and 1 connector card. The catalog also carries **8 G-Stack connector contracts with 18 capabilities**, separately from those 135 cards.

Seven agents have `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `SKILLS.md`, `HEARTBEAT.md` and `MANIFEST.yaml`: CEO, CTO, Chief of Staff, Librarian, Interpreter, Dispatcher and Sentinel. Their definitions and town characters do not activate tenant agents. HeyZack's inspected enablement currently selects no agents.

Nine adapters are shipped under `adapters/`: `claude`, `codex`, `cursor`, `generic`, `grok`, `hermes`, `muse`, `openclaw` and `opencode`. `generic` stays within a tenant workspace; the coding wing currently permits Claude, Codex, Grok, OpenCode and Cursor. Adapter `verify:` fields remain visible in every render. Muse is a placeholder and needs confirmation before use.

Catalog cards are references and reviewed descriptions, not vendored upstream packages. Skill rendering writes the card's body into a runtime wrapper; it does not fetch or install the upstream implementation. Plugin rendering writes instructions and never installs a plugin.

## Role packs and current HeyZack scope

| Island | Wing pack | Current tenant intersection | Device acceptance needed |
|---|---|---|---|
| Mac Coding 01 | `superpowers`, `gsd`, `taste-skill`, `github-mcp`, `playwright-mcp` | All 5 selected; the first 3 are pointers | Validate pointers, pin dependencies, review runtime plan, then run a local coding artifact test |
| Mac Coding 02 | Same coding pack, separate node identity and work attribution | Same source allowlist; no device proof follows | Repeat installation and artifact proof on that Mac |
| Mac Creative | `design`: 10 modules covering taste, Layers, Lottie, Archify, GSAP, Lenis, React Bits, ThreeUI, Vanta and Figma MCP | Only `taste-skill` intersects the inspected enablement | Review remaining module choices, Figma access and a local creative artifact test |
| Mac Marketing | 50 `ms-` modules plus `emil-skills` and `executive-assistant`; Gmail, Slack and Drive are node connector options | 52 modules selected; none of those 3 connectors selected | Review connector choices and auth; prove a local draft artifact before any external delivery |

The node allowlist never enables a tenant module. The effective set is `tenant enabled IDs ∩ node allowed IDs`, followed by the current catalog disposition check. `hold` and `refuse` stay excluded. High-risk and approval-required actions still pass `skills/connector-gate`, even when their module is enabled.

## Transfer decisions

| Class | Package treatment | Evidence to retain |
|---|---|---|
| Snow Gloves platform | Include reviewed source: agents, first-party skills, workflows, catalog, adapters, CLI and game interface; transfer private node profiles separately | Source revision, bundle SHA-256, per-file hashes, schema/version and verification receipt |
| Private instance | Transfer separately through the reviewed private-data route: tenant choices, source pointers, node assignments and receipts | Private data root, reviewed scope, ownership and backup/restore receipt; never embed credentials in the public bundle |
| Existing host skill packs | Keep as pointers; resolve and validate on each target | Origin, version or revision, content digest, expected skill name and resolution result |
| Native Codex/Claude/OpenCode components | Record installed versions and required capabilities; install through the product's supported mechanism when needed | Package ID, marketplace, version, enabled state and a fresh device probe |
| MCP dependencies | Include reviewed launch specifications, not a claim that the server is installed | Binary/package version, checksum where applicable, launch probe, environment variable names and separate auth result |
| OAuth/API connectors | Package capability IDs and gate policy; authorize each target and tenant separately | Tenant enablement, allowed operation, auth method, expiry/check result and approval ticket when required |
| Held/refused modules | Carry their disposition and reason as reference only | Catalog revision and reviewed decision; no render/install/activation |

The current host has 20 enabled Codex plugin entries with cached manifests, 14 Claude installation registry entries and 8 OpenCode plugin declarations. These inventories describe this host; they are not a portable Snow Gloves default. Useful role-specific candidates include engineering/review for coding, design/media capabilities for creative work, marketing/productivity for marketing, and document/spreadsheet tools across roles. Review and pin a small chosen set per device instead of copying the complete host cache or configuration.

The host also records `claude-mem` in its Claude plugin registry, while Snow Gloves explicitly refuses that catalog card. Preserve the host's unrelated installation and exclude it from the Snow Gloves migration pack. Multiple Superpowers registrations likewise need version reconciliation before choosing a target pointer.

The canonical host skill index currently records 1,032 skills across 49 clusters. Preserve its hub/spoke structure: active hubs load at startup, spokes resolve on demand, and deferred or archived skills stay deferred or archived. Core PAI and other preserved skills also exist outside that index. Do not turn an index count into a complete migration or readiness claim.

## First coding-device gaps

- `github-mcp-server` is the reviewed coding launcher, but its executable was absent in the inspected local PATH. Its environment reference is a template; neither GitHub token variable was present in the audit process. Installation and authenticated read-only proof remain separate steps.
- Playwright's configured launcher is `npx -y @playwright/mcp@latest`. Pin a reviewed version for repeatable device setup before using that launcher as an installation receipt. A runtime that already supplies browser tools can remain the first local UI-test path.
- The Codex adapter still marks `plan_mode` and `paths.skills` for verification. The current native configuration must remain intact while a plan is reviewed.
- HeyZack has an enablement file, but no `runtime.yaml` was present during the audit. A dry-run command does not record a runtime decision or activate any of the seven agents.
- No G-Stack connector is enabled for the coding wing in the inspected profile. Host MCP availability and app login do not grant tenant access.

## Safe review commands

Run from the platform checkout. Set `SNOWGLOVES_DATA` to the private instance checkout on this device; the platform catalog and adapters still come from the platform source.

```bash
python3 -B scripts/onboard.py --list --category mcp --json
python3 -B scripts/onboard.py --data "$SNOWGLOVES_DATA" \
  --render-adapter codex --tenant heyzack --node coding \
  --out /tmp/snowgloves-coding01-adapter-review
python3 -B scripts/onboard.py --data "$SNOWGLOVES_DATA" \
  --render-adapter claude --tenant heyzack --node coding \
  --out /tmp/snowgloves-coding01-claude-review
python3 -B scripts/onboard.py --data "$SNOWGLOVES_DATA" \
  --render-adapter opencode --tenant heyzack --node coding \
  --out /tmp/snowgloves-coding01-opencode-review
```

All commands above are dry runs: no `--write`, no downloads and no runtime start. The Codex dry run was executed successfully on 9 October: five effective modules, zero agents, three pointer skips and three proposed files. The review directory remained absent. A reviewed isolated write can then produce inspectable files without changing the native host configuration; a real adapter write follows the recorded runtime and path decision.

The first job receipt should bind a unique job ID, the canonical island ID, tenant, capability, start/end times, source revision, actual command result and artifact digest. Observed work can then animate that island's crew. A planned capability or local UI interaction must not be emitted as live fleet activity.

## Portable capability manifest

Use a manifest alongside the existing bundle and render manifests; the fields below describe the transition contract, not an implemented installer feature:

- `schema`, `createdAt`, `sourceRevision`, `bundleSha256` and `catalogSha256`.
- `islandId`, `wing`, `tenant`, `runtime`, `adapterVersion` and unresolved adapter fields.
- `enabledIds`, `nodeAllowedIds`, `effectiveIds`, chosen agent IDs and excluded IDs with reasons.
- Per component: `id`, `category`, `disposition`, `origin`, `version` or `revision`, `digest`, `transferMode` and dependency IDs.
- Separate `sourceAvailable`, `installed`, `configured`, `authenticated` and `deviceProven` results, each with `checkedAt` and evidence reference.
- Connector capability IDs, auth method and environment variable **names**; never token values, session cookies, raw host configuration or account secrets.
- Owned output files, expected hashes, reviewed plan digest, backup/rollback references and the first-job receipt.

For the other three Macs, copy the reviewed package and chosen private scope, resolve host pointers, repeat the dry run and installation proof, authenticate only selected connectors, and produce a fresh node-specific artifact receipt. Do not reuse Mac Coding 01's identity, credentials or device acceptance results.

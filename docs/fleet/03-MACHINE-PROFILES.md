# 03 — Machine profiles (wings)

Three Mac minis, three wings. Each wing is one file, `nodes/<wing>/node.yaml` (schema `snowgloves.node.v1`, documented in `nodes/SCHEMA.md`). The file says which runtimes that machine runs, which catalog ids it is allowed to serve, and how its MCP servers launch. Shared names (hostnames, overlay, ports, operator users) come from `fleet.yaml`.

The wing axis sits **beside** the tenant axis, not above it:

- `tenants/<slug>/enabled.yaml` says what a tenant has turned on. It is the only file `skills/connector-gate` reads. Unchanged.
- `nodes/<wing>/node.yaml` says what a machine may serve. It enables nothing.
- A render on a machine is the **intersection**: `enableable(enabled.yaml[tenant] ∩ node.modules[wing])`, plus the node's MCP launch specs for the ids that survive.

## The three files

| Wing | Host | Operator | Primary | Runtimes | Hosts | Serves |
|---|---|---|---|---|---|---|
| `marketing` | `marketing-mac` | `sg-marketing` | claude | claude, codex, grok, cursor | nothing (consumes the gateway) | 50 `ms-*` skills, `emil-skills`, `executive-assistant`; connectors `gmail`, `slack`, `google_drive` |
| `design` | `design-mac` | `sg-design` | claude | claude, cursor, codex | nothing | `taste-skill`, `layers`, `text-to-lottie`, `archify`, `gsap`, `lenis`, `react-bits`, `threeui`, `vanta`, `figma-mcp` |
| `coding` | `coding-mac` | `sg-coding` | claude | claude, codex, grok, opencode, cursor | OmniRoute `:20128`, Hermes `:4100` (always on) | `superpowers`, `gsd`, `taste-skill`, `github-mcp`, `playwright-mcp` |

Every wing points its `gateway.url` at `http://coding-mac:20128`; the coding Mac itself uses `127.0.0.1`. `gateway.key_ref` is a Keychain item name (`keychain:snowgloves-gateway-<wing>`), never a key.

### What lands on each wing

**Marketing.** Every `marketingskills` card (`ms-ab-testing` … `ms-video`, all disposition `add`) plus the two packs. Each enabled skill renders as `~/.claude/skills/<id>/SKILL.md` (or the runtime's equivalent). The three connectors are served by the G-Stack fabric: nothing installs, and they are **not** added by `enable --node marketing`; a tenant enables `gmail`/`slack`/`google_drive` itself, and every send still waits on `connector-gate` approval. No MCP servers.

**Design.** Four installable skills (`layers`, `text-to-lottie`, `archify`, plus the Figma MCP) and six pointers. `figma-mcp` launches with `npx -y figma-developer-mcp --stdio` and reads `FIGMA_API_KEY` from the `sg-design` environment.

**Coding.** Two MCP servers (`github-mcp`, `playwright-mcp`) and three pointers. `github-mcp` reads `GITHUB_PERSONAL_ACCESS_TOKEN` from the `sg-coding` environment or Keychain. `spec-kit` is on hold and `xmcp` is high-risk/approval, so neither is in the profile; add them to a node only after the catalog disposition changes.

### Pointer cards: the runtime installs them itself

`superpowers`, `gsd`, and `taste-skill` are disposition `pointer`: the host already provides them, so Snow Gloves renders nothing for them (the render prints `skip <id>: pointer (reference only, nothing to install)`). They stay in the wing's `modules` so the intersection and the rules block show they belong on the machine. Install them with the runtime's own mechanism:

| Id | Upstream | Install |
|---|---|---|
| `superpowers` | https://github.com/obra/superpowers | see card (`catalog/cards/superpowers.md`): the host loads it as a Claude/Cursor plugin; do not add a second copy |
| `gsd` | https://github.com/gsd-build/get-shit-done | see card: already the planning spine (`.planning/`); do not install a second pipeline |
| `taste-skill` | https://github.com/Leonxlnx/taste-skill | see card: present locally as `taste-skill` / `stitch-design-taste` in the host design cluster |

The card bodies carry provenance, not install commands, so the exact runtime command is whatever the host's plugin manager uses for that upstream.

### MCP launch precedence and secrets

For an MCP id the launch spec is chosen as `node.mcps[id]` > the card's `mcp:` block (`catalog/cards/<id>.md`) > a `FILL:` placeholder. The three MCP cards and the node files currently agree, so the node block is a redundancy you can edit per machine (a Docker image, a pinned version) without touching the catalog.

`env` values are variable names only (`"${FIGMA_API_KEY}"`); validation rejects anything else. Secrets live in the operator user's environment or Keychain on that Mac. The rendered `.mcp.json` / `config.toml` / `opencode.json` is safe to copy.

## Commands

Validate and inspect:

```bash
python3 scripts/fleet/node_profile.py list
python3 scripts/fleet/node_profile.py show coding
```

Give every registered tenant the marketing wing's skills (additive, idempotent; hold/refuse ids are rejected; connectors are not touched):

```bash
python3 scripts/fleet/node_profile.py enable --all-tenants --node marketing
```

Dry-run a render into a scratch folder and inspect the manifest:

```bash
python3 scripts/fleet/node_profile.py render --tenant heyzack --node marketing --runtime claude --out /tmp/check
cat /tmp/check/tenant/runtime/marketing/claude/render.json      # after --write
```

The same through `onboard.py` (`--node` defaults to `$SNOWGLOVES_NODE`, which each Mac sets to its wing):

```bash
python3 scripts/onboard.py --render-adapter claude --tenant heyzack --node marketing --write
```

What a render does on a wing:

1. refuses if the runtime is not in `node.runtimes` or the tenant is not in `node.tenants` (exit 1);
2. prints `skip <id>: not in wing profile <wing>` for tenant ids the wing does not serve, and `skip <id>: not enabled for tenant <slug> (run scripts/fleet/node_profile.py enable --tenant <slug> --node <wing>)` for wing ids the tenant has not enabled;
3. writes the runtime files as a plain render would, with the node's MCP specs, a per-tenant tagged rules block (`<!-- snowgloves:start tenant=<slug> -->`) that names the wing and links the tenant's real `context/*.md` files;
4. writes `tenants/<slug>/runtime/<wing>/<runtime>/render.json` with `"wing"` and `"effective": [ids]`. That folder is machine output; keep `tenants/*/runtime/` gitignored.

Exit codes: `0` ok, `1` usage or refusal, `2` the node file failed validation (`show <wing>` prints why).

## Adding or changing a wing

1. Edit `nodes/<wing>/node.yaml`. Use only ids that `python3 scripts/onboard.py --list` shows under OFFERED or POINTER.
2. `python3 scripts/fleet/node_profile.py show <wing>` must say `validation: valid`. `tests/test_nodes.py::test_real_nodes_validate_against_real_catalog` checks the same thing in CI.
3. A new wing name needs `fleet.yaml` and `WINGS` in `scripts/lib/nodes.py` updated together; the three current wings are the closed set.

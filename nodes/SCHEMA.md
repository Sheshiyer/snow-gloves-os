# Node (wing) schema

Each file `nodes/<wing>/node.yaml` describes **one machine wing**: a Mac mini that runs a fixed set of runtimes and is allowed to serve a fixed set of catalog ids. Schema id: `snowgloves.node.v1`. The loader and validator live in `scripts/lib/nodes.py`; `scripts/onboard.py --node` and `scripts/fleet/node_profile.py` use them. The shared inventory (hostnames, overlay names, ports, operator users) is `fleet.yaml`; a node file repeats the few names it needs so it can be read on its own.

A node **never enables anything**. The tenant's `tenants/<slug>/enabled.yaml` stays the single authority that `skills/connector-gate` reads. The node only narrows what a given machine renders.

## Merge rule (intersection)

```
render(tenant, wing, runtime) = enableable( enabled.yaml[tenant].modules ∩ (node.modules ∪ node.connectors) )
                                + node.mcps[id] launch specs for the ids that survive
```

- An id enabled for the tenant but absent from the wing is skipped (`skip <id>: not in wing profile <wing>`).
- An id listed by the wing but not enabled for the tenant is skipped (`skip <id>: not enabled for tenant <slug> (run scripts/fleet/node_profile.py enable --tenant <slug> --node <wing>)`).
- Hold and refused ids never render, whatever either file says.
- Tenant order is preserved; duplicates are dropped.

`scripts/fleet/node_profile.py enable --node <wing>` adds the wing's `modules` to a tenant's `enabled.yaml` (additive, idempotent, re-checked against the catalog). It never adds `connectors`; those are enabled per tenant by hand.

## Fields

| Key | Required | Values |
|---|---|---|
| `schema` | yes | `snowgloves.node.v1` |
| `wing` | yes | `marketing` \| `design` \| `coding`; must equal the folder name |
| `hostname` | yes | the machine's hostname, as in `fleet.yaml` (`coding-mac`) |
| `overlay` | no | overlay/MagicDNS name, usually the same as `hostname` |
| `location` | no | free text (`paris-office`) |
| `always_on` | no | `true` \| `false`. The gateway host is `true` |
| `services` | no | list of `{id, port}` this machine hosts (`omniroute: 20128`, `hermes: 4100`). Empty for wings that only consume the gateway |
| `operator_user` | yes | the day-to-day local user (`sg-<wing>`); `sg-admin` is the shared admin and never appears here |
| `primary` | yes | the default runtime; must be in `runtimes` |
| `runtimes` | yes | non-empty list of adapter ids (`adapters/<id>/adapter.yaml`). A render for a runtime outside this list is refused |
| `modules` | yes | catalog ids this wing may serve. Every id must exist in `catalog/modules.json` with disposition `add` or `pointer`; `hold` and `refuse` ids fail validation. Pointer ids render nothing (the runtime installs them itself) but still count toward the allow-list |
| `connectors` | no | G-Stack connector ids (`gmail`, `slack`, `google_drive`, …) the wing serves. They widen the allow-list for a render but are never auto-enabled |
| `mcps` | no | mapping `id -> launch spec`. The id must appear in `modules` (or `connectors`); a spec is `{command, args?, env?}` or `{url}`. **`mcps` never enables anything**; it only says how an MCP that is already enabled launches on this machine |
| `tenants` | no | `all` (default) or a list of `{slug, project?}` entries. A wing that lists tenants refuses renders for any other slug. `project` pins the `{project}` folder for that tenant on this machine |
| `gateway` | no | `{url, key_ref}`. `url` is the OmniRoute endpoint the wing talks to (`http://coding-mac:20128`; the host itself uses `127.0.0.1`). `key_ref` is a **reference** (`keychain:snowgloves-gateway-<wing>`), never the key |
| `remote_access` | no | mapping: `remote_management`, `ssh`, `allowed_users`. Documentation for the machine setup; nothing reads it at render |

Validation (`nodes.validate_node`) checks all of the above. With an `adapters_dir` it checks `runtimes` against the shipped adapters; with a catalog it checks `modules` and `connectors` through `onboard.resolve_ids`, so the refusal text matches `--enable`.

## MCP launch precedence

For an `mcp`/`connector` id that survives the intersection, the launch entry written into the runtime's MCP config is chosen in this order:

```
node.mcps[id]   >   card.mcp (catalog/cards/<id>.md front matter)   >   FILL: placeholder
```

The card's block is the upstream default; the node's block is the machine's override (a different binary, a Docker image, a pinned version). When neither exists the render writes `command: "FILL: launch command for <id> (see <repo>)"` and prints a note.

### Env values are variable names

`env` maps a variable name to a `${VAR}` reference and nothing else:

```yaml
mcps:
  github-mcp:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_PERSONAL_ACCESS_TOKEN}"
```

Validation rejects any `env` value that is not of the form `${NAME}`. The real value lives in the operator user's environment or Keychain on that machine; the rendered config stays safe to commit or copy. For OpenCode the block is written as `environment`; other runtimes keep `env`.

## `project` precedence

`{project}` in adapter paths (`{project}/.mcp.json`, `{project}/CLAUDE.md`, …) resolves, first match wins:

1. `--project DIR` on the command line
2. `node.tenants[<slug>].project` (when `tenants` is a list and the entry names one)
3. `tenants/<slug>/runtime.yaml` → `preferences.project` (unless it is a `FILL:`)
4. the tenant folder `tenants/<slug>/`

## Render output

- Runtime files land where the adapter says (`~/.claude/skills/<id>/SKILL.md`, `{project}/.mcp.json`, …), exactly as a plain render; with `--out DIR` they land under `DIR/home`, `DIR/project`, `DIR/tenant`.
- The rules block in `CLAUDE.md` / `AGENTS.md` is tagged per tenant (`<!-- snowgloves:start tenant=<slug> -->` … `<!-- snowgloves:end tenant=<slug> -->`) so several tenants can share one file; a legacy untagged block is migrated once. The block names the wing and links (never inlines) the tenant's `context/{voice,offer,customer,company}.md` files that hold real text.
- The manifest and plugin notes go to **`tenants/<slug>/runtime/<wing>/<runtime>/render.json`** (and `plugins.md`). The manifest adds `"wing"` and `"effective": [ids]` to the usual `snowgloves.render.v1` fields. This path is machine output and belongs in `.gitignore` (`tenants/*/runtime/`), not in the repo.

## Commands

```bash
python3 scripts/fleet/node_profile.py list
python3 scripts/fleet/node_profile.py show coding
python3 scripts/fleet/node_profile.py enable --all-tenants --node marketing
python3 scripts/fleet/node_profile.py render --tenant <slug> --node marketing --runtime claude --out /tmp/check
python3 scripts/onboard.py --render-adapter claude --tenant <slug> --node coding --write    # same, via onboard
SNOWGLOVES_NODE=coding python3 scripts/onboard.py --render-adapter claude --tenant <slug>   # the wing's default
```

Exit codes for `node_profile.py`: `0` ok, `1` usage or refusal (unknown wing, runtime not in the wing, tenant not served), `2` the node file failed validation.

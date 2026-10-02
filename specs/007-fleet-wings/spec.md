# Fleet wings: three Mac minis by function, remote access, Paris gateway handoff

Status: implemented on the authoring seat, 2026-10-02. Physical acceptance on the
Paris minis is pending and is its own receipt. Extends spec 005 (node bootstrap,
not replaced) and consumes spec 006 (Axtech brands as tenants). Roadmap R14;
relates to issue #20. This feature owns which brand runs on which machine with
which runtime. It does not own OmniRoute configuration, provider sessions, or
organization RBAC.

## Goal

Three Paris Mac minis, one per function (marketing, design, coding), share one
gateway and one overlay. A brand is enabled on a wing and rendered into a runtime
with one command, the same way on every mini. A mini can tell its operator whether
it is wired as its wing says. The founder's current mini authors the configuration
and hands the gateway to the Coding Mac without retyping anything.

## Inventory

`fleet.yaml` (schema `snowgloves.fleet.v1`) is the inventory: names only, no
secrets, no IP addresses. Tailscale MagicDNS resolves the overlay names.

| Wing | Overlay name | Always on | Operator user | Services |
|---|---|---|---|---|
| marketing | marketing-mac | no | sg-marketing | none |
| design | design-mac | no | sg-design | none |
| coding | coding-mac | yes | sg-coding | OmniRoute :20128, Hermes :4100 |

`sg-admin` is the local admin on every mini. The authoring seat (the founder's
current mini) has role `staging` and is not a wing.

## Two-axis model

Tenant is the brand axis. `tenants/<slug>/enabled.yaml` lists the modules a brand
has admitted and remains the connector-gate authority. Nothing in this feature
widens it.

Node is the machine axis. `nodes/<wing>/node.yaml` (schema `snowgloves.node.v1`)
says which runtimes a wing offers, which modules may run on that machine, the MCP
server specs the wing provides (command, args, environment variable names), which
tenants it serves, the gateway URL and key reference, and the remote-access
posture. The profile enables nothing by itself.

render(tenant, wing, runtime) = enableable(enabled ∩ node.modules) + node.mcps,
written into the runtime adapter's paths (`adapters/<runtime>/adapter.yaml`).
`enableable` keeps the catalog rule: `hold` and `refuse` cards never render. A
runtime not listed in `node.runtimes` is refused. An MCP with a spec in node.yaml
renders complete; `FILL:` appears only where neither the card nor the node knows
the value. `enable` adds a wing's modules to a tenant's enabled.yaml additively
and is idempotent; the founder still owns what a brand admits.

The gateway is one per fleet. The Coding Mac hosts OmniRoute on :20128 and Hermes
on :4100. Other wings reach `http://coding-mac:20128` over Tailscale; the Coding
Mac itself uses `http://127.0.0.1:20128`.

## Ten-step human flow

1. Company: confirm the legal entity and the portfolio root (Thoughtseed, Axtech).
2. Apple Account: one company Apple Account for the three minis.
3. Tailscale: install on the authoring seat and each mini; join as the overlay names.
4. Remote access: Remote Management (ARD), Screen Sharing and SSH on each wing,
   limited to that wing's operator user (`remote_access.sh`, dry-run first).
5. Machine profile: review `nodes/<wing>/node.yaml`; `fleet doctor` reads it.
6. Runtimes: install the wing's runtimes; each config points at the gateway URL.
7. Gateway: export the kit on the authoring seat, import on the Coding Mac, verify.
8. Brands: `make fleet-enable` a brand on a wing, then `make fleet-render` per runtime.
9. Team access: wing operator users, Apple Account sharing, approvals with an actor.
10. Operate: `make fleet-doctor`, `gateway_client.py status`, approvals with `--actor`.

The step documents live under `docs/fleet/`; start at `docs/fleet/README.md`.

## Paris handoff

The authoring seat exports a gateway kit (`gateway_kit.sh export`): the OmniRoute
configuration, the combo map, and the files a wing needs, with a checksum manifest
and no secrets inside the archive. The Coding Mac imports it, and `gateway_kit.sh
verify` compares the manifest. Provider OAuth sign-ins happen on the Coding Mac
itself under its operator user; tokens never travel in the kit. After the import,
the authoring seat stops acting as a gateway and remains a place to author and test.

## Acceptance criteria

- Sandbox render per wing x brand x runtime is correct: only enabled ∩ node.modules,
  plus node.mcps, in the adapter's format and paths.
- A runtime not in node.runtimes is refused with a clear message.
- No `FILL:` for an MCP that has a spec in node.yaml.
- `enable` is idempotent: a second run changes nothing.
- `gateway_client.py status` and `doctor` report the gateway state from a wing.
- `gateway_kit.sh export` then `verify` round-trips the manifest.
- `remote_access.sh --wing <wing>` prints a complete dry-run plan and changes nothing.
- `scripts/fleet/doctor.py` exits 0 on a wing whose node profile parses, whose
  gateway answers (local or fleet) and whose registered tenants all have a
  MANIFEST; Tailscale, remote access, SSH, Hermes and runtime configs are warnings.
- `approvals.py approve|reject` records `decided_by` from `--actor` or `SNOWGLOVES_ACTOR`.
- The test suite stays green: the 138 baseline plus the new tests.
- First-mini acceptance (physical) is a separate receipt: fleet doctor green on the
  mini, on-machine render, reboot continuity.

## Relationship to other specs

Spec 005 (node bootstrap) is not replaced. Its pilot `apply` consumes
`nodes/<wing>/node.yaml` as the machine profile and `fleet.yaml` as the inventory,
and its doctor contract (findings, exit codes, read-only default) is the target
the fleet doctor grows toward. Spec 006 supplies the brands: Axtech and its
branches are tenants, and their parent companies are confirmed before a wing
serves them.

## Open items

- Parent companies of the four brands flagged in the founder decisions are not
  confirmed; see `docs/fleet/05-BRANDS.md`.
- Provider terms for shared subscription seats are to be confirmed; until then the
  recorded decision stands.
- Apple Business Manager and managed Apple IDs come later; one company Apple
  Account for now.
- The authoring seat's hostname in `fleet.yaml` stays `FILL:` until the founder sets it.

# Implementation plan: fleet wings

## Evidence baseline

Before this session the repository had one axis, the tenant
(`tenants/<slug>/enabled.yaml`), plus runtime adapters, and no notion of which
machine a brand runs on. `scripts/doctor.sh` checked tools and ports 4100/3100
on one host. `scripts/approvals.py` recorded decisions without an actor. The
one-mini pilot (spec 005) was planning-only with 138 passing tests. Founder
decisions on 2026-10-02 fixed the overlay (Tailscale), the gateway host (the
Coding Mac in the office) and the account model (one company Apple Account,
`sg-<wing>` operator users). The decisions record is instance data and lives in
the private ops repo (`snow-gloves-ops/docs/fleet/DECISIONS.md`).

## Work packages

1. Inventory and decisions: `fleet.yaml` (instance data; `fleet.example.yaml` here);
   `docs/fleet/` (README, one document per human step).
2. Node profiles: `nodes/<wing>/node.yaml` for marketing, design, coding (schema
   `snowgloves.node.v1`); `scripts/lib/nodes.py` loads and validates a profile,
   intersects it with enabled.yaml, merges MCP specs, and refuses unlisted runtimes.
3. Node CLI: `scripts/fleet/node_profile.py` with `list`, `show`, `enable`
   (`--tenant` or `--all-tenants`, idempotent) and `render` (`--runtime`,
   `--write`, `--out` sandbox). `scripts/onboard.py` and `scripts/lib/adapters.py`
   accept the node merge so renders without a node keep working.
4. Gateway: `scripts/fleet/gateway_client.py` (`status`, `doctor`) and
   `scripts/fleet/gateway_kit.sh` (`export`, `verify`) for the gateway handoff.
5. Access: `scripts/fleet/remote_access.sh` (dry-run plan for ARD, Screen Sharing,
   SSH, the operator user and the `SNOWGLOVES_NODE` export; `--apply` on the mini)
   and `scripts/fleet/connect.sh <wing>` over Tailscale.
6. Operations: `scripts/fleet/doctor.py` (checks below), `scripts/approvals.py
   --actor`, Makefile `fleet-*` targets.
7. Planning spine: `specs/007-fleet-wings/`, roadmap R14, the planning handoff
   (private: `snow-gloves-ops/.planning/`), README pointers.

Packages were built in parallel by separate workers on the authoring seat with
disjoint file ownership. Package 6 and 7 code defensively against packages 1 to 5
landing later (tests use a temporary root).

## Fleet doctor checks

| Check | Evidence | Critical |
|---|---|---|
| wing | `--wing`, `SNOWGLOVES_NODE`, or the hostname matched against fleet.yaml wings | no |
| node-profile | `nodes/<wing>/node.yaml` exists, parses, declares the same wing | yes |
| tailscale | binary present and `tailscale status --json` reports BackendState Running | no |
| gateway | GET `/healthz` on fleet.gateway.url and on 127.0.0.1:<port>; either answer is enough | yes |
| remote-management | ARDAgent process, else com.apple.screensharing loaded | no |
| ssh | `systemsetup -getremotelogin`, else port 22 | no |
| hermes | TCP connect to the Hermes host and port (local on coding, overlay elsewhere) | no |
| tenants | every slug in `tenants/_registry.yaml` has `MANIFEST.yaml` | yes |
| runtime-<rt> | config file under `--home` exists and mentions the gateway URL (string search; contents never printed) | no |

Exit 0 when the critical checks pass, else 1. `--json` prints the list. Every
probe is best effort: a subprocess or socket error becomes a detail, never a crash.

## Verification

`python3 -m pytest -q tests/` runs the 138 baseline plus `tests/test_fleet_doctor.py`,
`tests/test_approvals_actor.py` and the node and gateway tests. `make -n fleet-doctor
fleet-render W=coding T=<brand> R=claude` shows the commands without running them.
On the authoring seat, `make fleet-doctor W=coding` passes the critical checks with
Tailscale (not installed) and Hermes (down) as warnings. Physical acceptance on an
office mini is a separate receipt and does not close issue #20 by itself.

## Open decisions

Brand parent companies; provider terms for account sign-ins; Apple Business Manager
timing; the authoring seat hostname; whether the fleet doctor adopts spec 005's
exit code 2 for held checks once the pilot CLI lands.

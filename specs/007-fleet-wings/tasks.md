# Task sequence: fleet wings

`done` means landed on the authoring seat in the 2026-10-02 session and covered by
the test suite. `pending` tasks need the founder or a physical office mini. No task
implies a commit, a push, an installation on a mini, or a provider sign-in.

| Task | Status | Scope |
|---|---|---|
| T01 | done | `fleet.yaml` inventory (instance data, private) and `fleet.example.yaml`; founder decisions recorded in the private ops repo |
| T02 | done | `nodes/<wing>/node.yaml` for marketing, design, coding (schema `snowgloves.node.v1`) |
| T03 | done | `scripts/lib/nodes.py`: load, validate, enabled ∩ node.modules, node.mcps merge, runtime refusal |
| T04 | done | `scripts/fleet/node_profile.py` list, show, enable, render; onboard and adapter integration |
| T05 | done | `scripts/fleet/gateway_client.py` status and doctor |
| T06 | done | `scripts/fleet/gateway_kit.sh` export and verify |
| T07 | done | `scripts/fleet/remote_access.sh` dry-run plan; `scripts/fleet/connect.sh` |
| T08 | done | `scripts/fleet/doctor.py`, `scripts/approvals.py --actor`, Makefile `fleet-*` targets, their tests |
| T09 | done | `docs/fleet/` step documents and README |
| T10 | done | `specs/007-fleet-wings/`, roadmap R14, planning handoff (private), README pointers |
| T11 | pending | Host-side operator steps: Tailscale on the authoring seat and three minis; ARD, Screen Sharing and SSH per wing (`remote_access.sh --apply` on the mini); `sg-<wing>` users; Apple Account sign-in; kit import on the Coding Mac and OAuth sign-ins there; dashboard password rotation; omniroute MCP key scope |
| T12 | in-progress (first mini accepted on the LAN; Tailscale, power policy, scoped keys, two more minis pending; receipts in the private ops repo) | Physical first-mini acceptance: `make fleet-doctor` green on each wing, on-machine render per wing x brand x runtime, reboot continuity; recorded separately from the spec 005 pilot |

Ownership follows the packages in plan.md. T11 belongs to the founder on the
minis. T12 is its own receipt and does not close issue #20 by itself.

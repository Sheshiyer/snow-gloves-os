---
name: connector-gate
description: "Use an external tool only when the tenant has enabled it, and wait for approval on high-risk actions. USE BEFORE any MCP tool, plugin tool, catalog skill, G-Stack capability, or third-party CLI that is not built into the runtime."
version: 0.1.0
author: Thoughtseed
license: MIT
metadata:
  snowgloves:
    tags: [connectors, mcp, approval, catalog]
    related_skills: [sg-onboard]
    ported_from: factor/skills/connector-gate
---

# Connector gate

Run this check before calling any MCP tool, plugin tool, catalog skill, or third-party CLI for a tenant. Tools built into the runtime don't need it: file reads, the runtime's own web fetch, and the Hermes bus (`scripts/hermes.py`).

## Procedure

1. Resolve the tenant slug. If you can't, stop and ask. Never assume `_demo`.
2. Read `tenants/<slug>/enabled.yaml` (schema `snowgloves.enabled.v1`).
   - If the file is missing, **nothing is enabled**. Stop.
   - Find the id under `modules:`. A catalog card id (for example `ms-cro` or `xmcp`) or a G-Stack connector capability id (for example `slack.post_message`) both count.
3. If the id is not listed, stop. Tell the founder the id is off, and give them the enable command: `python3 scripts/onboard.py --tenant <slug> --enable <id>`. Do not call the tool.
4. Look up the id in `catalog/modules.json`:
   - `disposition: hold` or `refuse` means **refuse**, even if someone hand-edited it into `enabled.yaml`. Quote the card `summary` as the reason. Hold and refused cards appear in the catalog but can never be enabled.
   - `disposition: pointer` means the card points at something the host already provides, or at a read-only reference (for example the `fk-*` playbooks). Read or use the host copy. Do not install a second copy.
   - `disposition: add` means allowed, subject to step 5.
5. Read `risk` and `approval` from the card, or from the capability in `connectors/g-stack/capabilities.yaml`. The action needs an approved ticket in `tenants/<slug>/approvals/` (see `scripts/approvals.py`) **before** the call when either of these holds:
   - `approval: yes`, or `risk: high`
   - the action is in one of these classes, whatever the card says:
     - money: spend, invoices, payroll, ads, or paid API calls
     - hiring, roles, or personal data
     - legal commitments
     - a public post, or an email, DM, or SMS to anyone outside the company
6. Reads through a connector are low risk only when the card says `risk: low` and `approval: no`.
7. Enabling or adding a connector is the founder's decision, made through onboarding. Never write credentials into `enabled.yaml`, `AGENTS.md`, or a card. Secrets live in the runtime's env or vault (`connectors/g-stack/auth.py`).

## Verification

Name the id, the `enabled.yaml` line you relied on, and the card's `disposition`, `risk`, and `approval`. If you stopped, say which rule fired: not enabled, hold or refuse, or approval pending.

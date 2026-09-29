# Snow Gloves OS: Operator Orientation & Executive Briefing Guide

## Executive Summary

**Snow Gloves OS** is a tenant-scoped operations platform designed to run business operations as if a dedicated, senior executive team were monitoring the business 24 hours a day, 7 days a week. The central design philosophy of the system is simple: **you keep the decisions**. The platform operates as a senior drafting team that prepares work, translates context, routes requests, and stages tasks—while leaving high-stakes approvals, spending, public publishing, and legal execution strictly in human hands.

The platform wraps your existing operating tools (via G-Stack connectors), tenant knowledge (via NVIDIA embeddings), domain judgment (an interpretation layer), and task orchestration (via Hermes event bus and Paperclip bridge). It is entirely **agent-agnostic**: operators can select their preferred agent runtime (such as Cursor, Claude Code, Codex, Hermes, Grok, or a generic fallback), and Snow Gloves renders its skills, Model Context Protocol (MCP) server configurations, and governance rules directly into that runtime’s native workspace format.

Onboarding is structured as an interactive, plan-mode interview that gathers tenant context without guessing or injecting unverified data. Missing facts are explicitly tagged with `FILL:` tags rather than assumed. Operational capabilities are managed through a structured catalog of 130 catalog cards governed by strict dispositions (`add`, `pointer`, `hold`, `refuse`). High-risk actions and outbound write operations are strictly gated by human approval. Day-to-day operations follow a "quiet week" model: routine workflows execute silently, drafts wait for human inspection, and the Sentinel agent conducts automated end-of-day health and drift sweeps.

---

## Key Theme Analysis

### 1. Operating Model: Senior Team Drafts, Human Decides
Snow Gloves OS structures business operations around seven functional "desks" (CEO, CTO, Chief of Staff, Librarian, Interpreter, Dispatcher, and Sentinel). Rather than acting as fully autonomous, unsupervised bots, these desks function as an executive support team:
*   **Drafting vs. Executing:** The system ingests external events (webhooks, email, calendar, support, internal tasks), interprets context, and drafts appropriate responses or artifacts.
*   **Human-in-the-Loop Governance:** High-risk actions—specifically involving spending money, posting publicly, handling sensitive personal data, or committing to legal agreements—require an explicit human decision ("one yes") before execution.

### 2. Runtime Neutrality via Adapter Architecture
Snow Gloves OS does not force an operator into a specific AI tool. Each supported environment has a dedicated configuration adapter (`adapters/<runtime>/adapter.yaml`) that maps skills, rules, and MCP servers into the native layout expected by that runtime:
*   **Supported Seats:** Hermes Agent, Claude Code, OpenAI Codex CLI, Cursor, OpenCode, Grok CLI, OpenClaw, Muse, and Generic fallback.
*   **Native Rendering:** When rendered, the system updates the runtime's local configuration files (such as `CLAUDE.md`, `.cursor/mcp.json`, or root `AGENTS.md` blocks) so the agent operates directly within the user's existing development or management seat.

### 3. Governed Module Catalog & Dispositions
The platform maintains a registry of 130 cards covering skills, playbooks, plugins, MCP servers, and connectors. To prevent operational drift or unauthorized tool installation, every card is classified under one of four non-negotiable dispositions:
*   **`add` (59 cards):** Approved modules ready for single-click enablement and local rendering.
*   **`pointer` (45 cards):** Reference material or host-provided capabilities that are made visible to the runtime as documentation without duplicating code installation.
*   **`hold` (14 cards):** Capabilities under review; visible on the dashboard but blocked from enablement until reviewed and explicitly promoted by the operator.
*   **`refuse` (12 cards):** Reviewed and rejected capabilities; permanently blocked from enablement.

### 4. Continuous Operational Guardrails ("A Quiet Week")
During normal operations, Snow Gloves OS operates unobtrusively:
*   **Silent Staging:** Routine processing occurs in the background. Drafts wait in designated workspaces for human review.
*   **Selective Escalation:** The platform only interrupts the operator when a predefined risk boundary is reached or explicit approval is required.
*   **Daily Drift Sweeps:** At the end of every day, the **Sentinel** desk performs an automated drift sweep over hook usage, fallbacks, and escalations, appending performance summaries to each agent's `EVOLUTION.md` file to drive iterative refinement.

---

## Key Quotes & Operational Context

> *"Run a business as if a senior team were watching it 24/7."*
*   **Operational Context:** Defines the primary value proposition of Snow Gloves OS. It emphasizes continuous monitoring and background execution without sacrificing managerial oversight.

> *"You keep the decisions; a senior team that drafts; you send, spend, and publish."*
*   **Operational Context:** The core directive governing human-agent boundaries. Agents handle synthesis, drafting, and workflow orchestration, but output that commits capital, updates public channels, or modifies external systems stays gated behind human authorization.

> *"FILL: when a fact is missing, never guess."*
*   **Operational Context:** The baseline rule during onboarding and context collection. If a company fact, target audience detail, or operational credential is unknown, the system writes `FILL: <missing fact>` into the harvest document rather than hallucinating plausible assumptions.

> *"Drafts wait, only crossed lines speak, Sentinel at the end of the day."*
*   **Operational Context:** The operational definition of a "quiet week." Operators are not spammed with intermediate agent notifications; communication occurs only upon exception, approval request, or during scheduled daily Sentinel feedback summaries.

---

## 10-12 Slide Deck for New Operators

### Slide 1: Title
*   **Header:** Snow Gloves OS
*   **Sub-header:** You Keep the Decisions
*   **Core Message:** Welcome to your operational platform. Snow Gloves OS is designed to manage day-to-day administrative, technical, and strategic workflows while leaving full decision-making control in your hands.

---

### Slide 2: What It Is
*   **Header:** A Senior Team That Drafts
*   **Operational Model:**
    *   **The Workflow:** You send, spend, and publish; the system researches, routes, and drafts.
    *   **Four Integrated Engines:**
        1.  *Connector Engine:* Wraps external tools and channels (Gmail, Calendar, Slack, Drive, PMS, Accounting, HRIS) via G-Stack connectors.
        2.  *Knowledge Engine:* Ingests, chunks, and indexes company context using tenant-isolated NVIDIA vector embeddings.
        3.  *Interpretation Engine:* Routes incoming events and requests through skill hooks and desk-specific judgment rules.
        4.  *Orchestration Engine:* Coordinates background tasks through the Hermes event bus (`:4100`) and Paperclip task bridge (`:3100`).

---

### Slide 3: First Hour
*   **Header:** Quick-Start Timeline
*   **Step-by-Step Guidance:**
    1.  **Install:** Clone the repository and run the setup script.
    2.  **Pick a Runtime:** Select the AI seat you already use (e.g., Cursor, Claude, Codex).
    3.  **Interview:** Run the plan-mode interview to capture tenant facts.
    4.  **Enable One Skill:** Choose a single skill card from the catalog to handle your first real operational job.

---

### Slide 4: Install
*   **Header:** Getting the Platform Running
*   **Terminal Setup:**
    ```bash
    git clone https://github.com/Sheshiyer/snow-gloves-os.git
    cd snow-gloves-os
    ./scripts/install.sh
    ```
*   **Desktop App Option:** A native Tauri v2 desktop app and visual wizard are available in `apps/onboarding` (`make app-install` / `make app-dev`).
*   **Version 0.2.0 Upgrade Note:** Platform version `0.2.0` introduces a new bundle identifier (`com.tryambakam.snowgloves.onboarding`). Existing `0.1.x` users must perform a fresh reinstallation from the desktop installer package (DMG/MSI), as over-the-air (OTA) updates will not auto-detect `0.2.0`.

---

### Slide 5: Pick a Runtime
*   **Header:** Native Seat Integration
*   **Supported Seats:** Cursor, Claude Code, OpenAI Codex CLI, Hermes Agent, Grok CLI, OpenCode, OpenClaw, Muse, or Generic fallback.
*   **How Adapters Work:** Snow Gloves reads `adapters/<runtime>/adapter.yaml` and writes configuration files directly into your runtime seat:
    *   *Claude Code:* Appends rules to `CLAUDE.md` and MCP entries to `.mcp.json`.
    *   *Cursor:* Generates `.cursor/rules/snowgloves.mdc` and updates `.cursor/mcp.json`.
    *   *Codex / Grok / OpenCode:* Writes rules blocks to `AGENTS.md` and MCP settings to respective config files.
    *   *Generic:* Writes all skills, MCP config, and rules directly into `tenants/<slug>/runtime/generic/` for manual export.

---

### Slide 6: The Interview
*   **Header:** Plan-Mode Onboarding Interview
*   **Command:** `make onboard-prompt R=<your-runtime>`
*   **Rules of Engagement:**
    *   **Plan Mode First:** The agent enters plan mode and asks questions one at a time using your runtime's native tool (e.g., `AskUserQuestion`, `AskQuestion`, `request_user_input`, `clarify`).
    *   **Strict Catalog Options:** The agent only presents options that exist in `catalog/modules.json`.
    *   **No Guessing (`FILL:`):** If an answer is unknown, the system writes `FILL: <missing detail>` into the document. `FILL:` lines are never treated as valid facts or auto-enabled IDs.

---

### Slide 7: The Harvest
*   **Header:** Applying Context & Enabling Modules
*   **Workflow:**
    1.  **Harvest Document:** The interview outputs `snowgloves-harvest.md` in your project folder.
    2.  **Apply Context:**
        ```bash
        python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant acme
        ```
        This creates tenant files, saves context into `tenants/acme/context/`, and writes `enabled.yaml` and `runtime.yaml`.
    3.  **Enable Cards:**
        ```bash
        python3 scripts/onboard.py --enable ms-copywriting --tenant acme
        ```
    4.  **Render Config:** Dry run with `--render-adapter <runtime>`, then finalize with `--write`.

---

### Slide 8: The Seven Desks
*   **Header:** Operating Desks, Not Technical Jargon
*   **Desk Breakdown:**
    *   **CEO Desk:** Defines top-level direction, approves strategic proposals, and reviews company positioning.
    *   **CTO Desk:** Handles technical infrastructure, codebase integrity, and architecture checks.
    *   **Chief of Staff:** Coordinates task routing, maps skill hooks across 69 routed skills, and prevents senior desks from getting bogged down.
    *   **Librarian:** Manages context intake, document chunking, and vector index searching via NVIDIA embeddings.
    *   **Interpreter:** Translates external incoming messages, webhooks, and events into categorized operational tasks.
    *   **Dispatcher:** Connects task definitions to execution runners and manages background jobs via Paperclip.
    *   **Sentinel:** Conducts compliance, security, and daily drift reviews across all operations.

---

### Slide 9: Modules & Gating
*   **Header:** Catalog Dispositions & Safety Gates
*   **Catalog Composition (130 Total Cards):**
    *   `add` (59 cards): Ready to enable and render into your runtime.
    *   `pointer` (45 cards): Reference materials or pre-installed host features.
    *   `hold` (14 cards): Blocked on dashboard until manually reviewed and promoted.
    *   `refuse` (12 cards): Permanently rejected modules; cannot be turned on.
*   **Risk & Approval Controls:**
    *   Every tool and connector contains `risk` (`low`, `medium`, `high`) and `approval` (`yes`, `no`) metadata.
    *   The `connector-gate` skill blocks any external tool call if the connector is not explicitly enabled in the tenant's `enabled.yaml`.
    *   High-risk actions and write permissions always pause for human approval.

---

### Slide 10: A Quiet Week
*   **Header:** Calm, Asynchronous Operations
*   **The Weekly Rhythm:**
    *   **Silent Preparation:** Drafts, summary reports, and task queues assemble quietly in the background.
    *   **Minimal Interruptions:** You are only notified when a predefined threshold is crossed or an explicit permission gate is hit.
    *   **End-of-Day Sentinel Sweep:** Run `make sentinel` daily (or via cron). The Sentinel analyzes daily hook usage, fallbacks, and escalations, appending performance summaries directly to each agent's `EVOLUTION.md` file for continuous self-improvement.

---

### Slide 11: Approvals
*   **Header:** Strategic Human Control Points
*   **Four Non-Negotiable Gates ("One Yes Required"):**
    1.  **Financial Spend:** Any transaction, budget alteration, or paid API activation.
    2.  **Public Publishing:** Outbound social posts, blog uploads, marketing emails, or external announcements.
    3.  **Personal Data Handling:** Exporting or processing sensitive customer/employee records.
    4.  **Legal Commitments:** Finalizing contracts, terms, or formal agreements.

---

### Slide 12: Closing
*   **Header:** Resources & Immediate Next Steps
*   **Key Resources:**
    *   **Documentation & Modules Web Dashboard:** `https://sheshiyer.github.io/snow-gloves-os/`
    *   **Product Code Repository:** `https://github.com/Sheshiyer/snow-gloves-os.git`
*   **Your Action Plan for Today:**
    1. Clone the repo and run `./scripts/install.sh`.
    2. Pick one operational seat and generate your interview prompt (`make onboard-prompt R=<runtime>`).
    3. Complete the interview, apply the harvest, and enable **one single skill** for one specific desk job.

---

## Actionable Operational Cheat Sheet

### Core Terminal Commands

| Task | Command |
| :--- | :--- |
| **System Bootstrap** | `./scripts/install.sh` |
| **Pre-flight Diagnostic** | `make doctor` |
| **Generate Interview Prompt** | `make onboard-prompt R=<runtime>` *(e.g., `claude`, `cursor`, `codex`, `hermes`)* |
| **Apply Interview Harvest** | `python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant <slug>` |
| **List Catalog Modules** | `python3 scripts/onboard.py --list [--category skills\|mcp\|plugin\|playbook]` |
| **Enable Catalog Module** | `python3 scripts/onboard.py --enable <card-id> --tenant <slug>` |
| **Dry-Run Adapter Render** | `python3 scripts/onboard.py --render-adapter <runtime> --tenant <slug>` |
| **Write Adapter Render** | `python3 scripts/onboard.py --render-adapter <runtime> --tenant <slug> --write` |
| **Start Event Bus (Hermes)** | `make hermes` *(runs on port `:4100`)* |
| **Run Daily Drift Sweep** | `make sentinel` |
| **Full System Smoke Test** | `make smoke` |

### Key Tenant Directory Structure

```text
tenants/<slug>/
├── enabled.yaml              # Enabled catalog modules, connectors, and agents
├── runtime.yaml              # Runtime choices, primary selection, preferences
├── sources.yaml              # Ingested documentation sources and paths
├── context/                  # Structured business context
│   ├── company.md            # Target product/company positioning
│   ├── customer.md           # Ideal customer profile
│   ├── offer.md              # Pricing and product specs
│   ├── owner.md              # Executive leadership background
│   ├── voice.md              # Brand tone and communication rules
│   └── open-questions.md     # Outstanding FILL: items requiring resolution
└── raw/
    └── harvest.md            # Exact copy of the initial onboarding harvest
```
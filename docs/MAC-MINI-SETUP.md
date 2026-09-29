# Mac Mini first hour (product, not a build)

This is the checklist for a **new Mac Mini** that should feel like Snow Gloves in about 90 minutes. You are using the product. You are not compiling the desktop app, signing a DMG, or standing up production Paperclip / Gmail / NVIDIA.

Human guide: [snow-gloves-wiki](https://snow-gloves-wiki.vercel.app). Catalog dashboard (not the guide): https://sheshiyer.github.io/snow-gloves-os/.

## What “the glove” means tomorrow

The glove is: **your agent runtime in plan mode → harvest file → tenant on disk → one skill rendered into that runtime → Hermes listening so events have a bus → `make walk` GREEN on the Chief of Staff graph.** Smoke passing without a harvest is only the plumbing. The Mini proof of the loop is `make walk`, then optional `make graph-upgrade` dry-run — not live Gmail.

Skip live mail, live NVIDIA embeddings, and a real Paperclip host. Those are later.

## Bill of materials (install these first)

Do this in order. Stop if a step is missing — later steps fail in confusing ways.

| # | App / tool | Why | Skip? |
|---|---|---|---|
| 1 | **Cursor** *or* **Claude Code** | The interview only works *inside* a runtime that can stay in plan mode and ask one question at a time. Install **before** you clone. | No. This is the glove. |
| 2 | Homebrew | Cleanest way to get git / python / node on a blank Mini. | You can install git, Python 3, and Node 20+ some other way. |
| 3 | Git | Clone the product repo. | No, unless you already have a zip of the repo. |
| 4 | Python 3 | `install.sh`, `onboard.py`, Hermes, smoke. | No. |
| 5 | Node 20+ and npm | `paperclipai` CLI (`npm install -g paperclipai`). The CLI is not a running Paperclip *host*. | No. `install.sh` refuses to start without `node` / `npm`. |
| 6 | curl | Smoke posts to Hermes. | Usually already on macOS. |
| 7 | (Optional) GitHub Desktop / `gh` | Only if you prefer a GUI clone. | Yes. |
| 8 | (Optional) v0.2.0 **DMG** from [GitHub Releases](https://github.com/Sheshiyer/snow-gloves-os/releases) | Desktop wizard: doctor, tenant folder, Paperclip UUID field, sources, `make smoke`. It does **not** replace the plan-mode interview. | Yes. Prefer clone + CLI for the first hour. |

**Do not install for the first hour:** Xcode, Rust, Apple Developer certs, NVIDIA NIM, a Gmail OAuth app, launchd plists, Docker, Paperclip server, inference-sh skill packs.

Apple ID / iCloud is only needed if you fetch Cursor or Claude from the Mac App Store. Direct downloads work without that.

### Runtime: pick one and finish it

| If you pick | Install | How you enter plan mode |
|---|---|---|
| **Cursor** (recommended on a Mini you will edit on) | [Cursor](https://cursor.com) desktop app, then open this repo as the project | Mode picker or Shift+Tab → Plan. Question tool: `AskQuestion`. |
| **Claude Code** | `claude` CLI from Anthropic’s docs | Shift+Tab until it says plan mode, or `claude --permission-mode plan`. Question tool: `AskUserQuestion`. |

Install **one** fully (signed in, can open a folder, can enter plan mode). Do not spend the hour installing Codex, Grok, OpenCode, and Hermes Agent as well.

## Path A — clone (default, 90 minutes)

1. Open Terminal.

   ```bash
   # if Homebrew is not installed:
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install git python node
   ```

2. Clone **this** product (not an old modular copy):

   ```bash
   git clone https://github.com/Sheshiyer/snow-gloves-os.git
   cd snow-gloves-os
   git checkout chore/consolidate-modular   # until this lands on main
   ```

3. Bootstrap. Expect printed steps, **not** a live system and **not** the old interactive tenant prompt:

   ```bash
   ./scripts/install.sh
   ```

   If `import yaml` fails, `install.sh` tries `pip install pyyaml` before it reads `config/snowgloves.yaml`. If pip is blocked (PEP 668), run `python3 -m pip install --user pyyaml` and retry.

   If an older `install.sh` still launches `make onboard`, cancel it (Ctrl+C after deps) and continue from step 4.

4. Preflight and plumbing:

   ```bash
   make doctor
   make smoke
   ```

   Doctor **warnings** you can ignore tomorrow: `paperclipai` until install finished; port 3100 not listening; `NVIDIA_API_KEY` unset. Doctor **failures** you cannot ignore: missing `python3` / `node` / `pyyaml` / repo files.

   Smoke starts Hermes, posts `/test/e2e`, dry-runs the Paperclip bridge, embeds a sample with **`SNOWGLOVES_EMBED_BACKEND=stub`**, runs Sentinel, then **stops** Hermes. That is correct. You will start Hermes again at the end and leave it up.

   Then prove the skill graph with a program, not a live mailbox ([Hanako: loop vs graph](https://x.com/hanakoxbt/status/2091515787366306154)):

   ```bash
   make walk                 # GREEN = expected agent+hook, native skills on disk, inner loop max 3
   make graph-upgrade        # optional dry-run: constraints + hook diffs (hooks are not auto-merged)
   ```

   `make walk` writes `tenants/_demo/audit/graph-walk.json`. `make graph-upgrade` does **not** apply hook diffs unless the tenant `approval_mode` is `allow-graph-write`; otherwise it queues an approvals ticket. `scripts/ingest.py` still only plans wiki files for the Librarian — it does not mutate hooks.

5. Open the **same folder** in Cursor (or `cd` into it and run `claude`). Stay in **plan mode**. Print and paste the interview:

   ```bash
   make onboard-prompt R=cursor    # or R=claude
   ```

   Answer one question at a time. Enable **one** skill for the first job (good default: `ms-copywriting`). Do **not** enable Gmail or other write connectors. Do **not** invent Paperclip company UUIDs. The only file the interview should write is `snowgloves-harvest.md`.

6. Apply, enable if the harvest skipped the skill, render:

   ```bash
   python3 scripts/onboard.py --apply-harvest snowgloves-harvest.md --tenant <slug>
   python3 scripts/onboard.py --enable ms-copywriting --tenant <slug>
   python3 scripts/onboard.py --render-adapter cursor --tenant <slug>
   python3 scripts/onboard.py --render-adapter cursor --tenant <slug> --write
   ```

   Use `claude` instead of `cursor` if that is the runtime you installed. Dry-run first, then `--write`.

7. Leave the bus up in a dedicated Terminal tab until you shut the Mini down:

   ```bash
   make hermes
   ```

   Hermes is **not** a LaunchAgent. Closing that tab stops events. There is no `make hermes-stop` needed if you use Ctrl+C; `make kill-hermes` frees port 4100 if something else grabbed it.

You are done when: harvest exists, `tenants/<slug>/enabled.yaml` lists the skill, the runtime folder has a `render.json`, and `lsof -i tcp:4100` shows Hermes.

## Path B — DMG wizard (optional extra, not the glove)

v0.1.x OTA **cannot** jump to 0.2.0. Identifier is `com.tryambakam.snowgloves.onboarding`. Trash any 0.1.x app first.

1. Install a **notarized** 0.2.0 DMG from GitHub Releases (Gatekeeper will fight an unsigned local build).
2. The wizard still shells into **this repo** (`scripts/doctor.sh`, `tenant_new.sh`, `make smoke`). Put the clone on disk first, or the app’s repo-root lookup is wrong.
3. Paperclip UUID: **leave empty**. `paperclip.tn.local:3100` is a placeholder (phase T5).
4. After the wizard, you still need Path A steps 5–7 (runtime + harvest + render + leave Hermes running). The Modules tab is the catalog, not the interview.

## Honest gaps (do not try to “finish” these tomorrow)

| Gap | What happens | What to do in 90 minutes |
|---|---|---|
| `paperclip.tn.local` is not a real host | Doctor warns port 3100 idle. Live `paperclip_bridge` without `--dry-run` cannot create tasks. | Accept the warning. Smoke already dry-runs. Do not bind a fake company UUID. |
| NVIDIA embeddings | Without `NVIDIA_API_KEY`, doctor warns; smoke **forces the stub**. | Leave the key unset. Stub is the intended first-hour path. |
| Live Gmail | G-Stack Gmail capabilities exist; there is no OAuth session on a blank Mini. | Do not enable Gmail. First job is a local skill, not mail. |
| `inference-sh/agent-skills@…` | Agent `SKILLS.md` files point at that prefix; those packs are **not vendored** in this repo. Catalog cards are pointers. | Enable an `add` skill such as `ms-copywriting`. Render writes the card’s `SKILL.md`, not the upstream inference-sh tree. |
| Hermes is not launchd | `make hermes` is foreground. `make smoke` kills Hermes when it finishes. | Dedicated Terminal tab after smoke. Re-run `make hermes` after reboot. |
| Desktop updater | 0.1.x will not see 0.2.0. | Fresh DMG only if you use the wizard. |

## If the interview is eating the clock

Keep the harvest tiny: tenant name + slug, owner in one sentence, `FILL:` on company/customer/offer, agents `interpreter` only, skills `ms-copywriting`, connectors `none`, runtime the one you installed, `approval_mode: always-ask`, `render: dry-run`. Then apply and `--write` anyway so the Mini has files, not a perfect company wiki.

## What not to do

- Do not run `make app-dev` / `make app-build` on the Mini. That needs Rust + Xcode and is for emulating the wizard on a **dev** Mac. See [`apps/onboarding/README.md`](../apps/onboarding/README.md).
- Do not enable a pile of modules “while we’re here.”
- Do not expect `make smoke` to keep Hermes running.
- Do not treat a green doctor as “the team is watching the business.” That starts after harvest + render + Hermes left up.

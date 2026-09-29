---
type: research
status: review
created: 2026-09-29
owner: ceo
related:
  - catalog/cards/
  - catalog/SCHEMA.md
  - tenants/_demo/wiki/systems/ecosystem-candidates.md
  - tenants/_demo/wiki/systems/skill-hook-crosswalk.md
  - tenants/_demo/wiki/systems/hands-pointers.md
  - tenants/_demo/wiki/creative/ig-harvest.md
  - tenants/_demo/wiki/ecosystem/HARVEST-2026-09-29.md
---

# Ecosystem review: 2026-09-29

This review covers every harvested item: the X bookmark harvest, the Field Theory taste packs, the Instagram saved harvest, [founders-kit](https://github.com/avinash201199/founders-kit), and [marketingskills](https://github.com/coreyhaines31/marketingskills). Each item now has a pointer card in `catalog/cards/`, and this doc gives the recommended disposition for each one, with the reason, the target agent and hook, and the runtimes it fits.

**Nothing is wired.** `workflows/skill-hooks.yaml` is unchanged. A card's `hooks:` field names the area the item *would* serve. Moving any item into routing takes a founder pick (see the end of this doc) and then a separate change.

## Counts

| | add | hold | refuse | pointer | total |
|---|---:|---:|---:|---:|---:|
| cards | 59 | 14 | 12 | 45 | 130 |

| skills | mcp | connector | plugin | playbook |
|---:|---:|---:|---:|---:|
| 77 | 3 | 1 | 13 | 36 |

By source: X harvest 23, Field Theory taste packs (not already in the X harvest) 11, Instagram 12, founders-kit 34 (one index card plus 33 categories), and marketingskills 50.

The dispositions work like this:

- `add` means the tenant can enable it through onboarding.
- `pointer` means the tenant can enable it, but the host already provides it or it is a read-only reference, so don't install a second copy.
- `hold` means it is listed but can't be enabled until the founder picks it and it passes a review.
- `refuse` means it is listed and can never be enabled.

The connector gate (`skills/connector-gate/SKILL.md`) refuses `hold` and `refuse` ids even if someone hand-edits them into `tenants/<slug>/enabled.yaml`.

Citation formats:

- An X citation is the Field Theory bookmark id, linked as `x.com/i/status/<id>`.
- An IG citation is the saved-post shortcode, linked as `instagram.com/p/<shortcode>/`.
- The "Risk" column shows the card's risk and whether it needs approval.

## 1. X bookmark harvest: ecosystem candidates

Source: the 456-bookmark deep pass on 2026-09-29. The Four-Signal scores come from `ecosystem-candidates.md`, and the hook mapping from `skill-hook-crosswalk.md`. Where a Field Theory pack exists, the card body names its path under `~/.fieldtheory/library/taste/skills/`.

| Card | Upstream | Citation | Disposition | Reason | Agent; hook | Runtimes | Risk |
|---|---|---|---|---|---|---|---|
| `superpowers` | [obra/superpowers](https://github.com/obra/superpowers) | [X 2035915909966229733](https://x.com/i/status/2035915909966229733) | **pointer** | Four-Signal 11/12. The host already loads it as a Cursor/Claude plugin, so a second copy under Snow Gloves would drift. | cto | claude, codex, cursor, opencode | low/no approval |
| `gsd` | [gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done) | [X 2035915909966229733](https://x.com/i/status/2035915909966229733) | **pointer** | Four-Signal 12/12 but the method is already here through the Temperance rail and vault GSD. | cto | claude, codex, cursor, opencode | low/no approval |
| `agent-skills` | [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | [X 2096252768633995734](https://x.com/i/status/2096252768633995734) | **hold** | Four-Signal 9/12. Useful, but the pack is broad; install one workflow at a time. | cto, librarian; `cto.innovation-and-adapt`, `librarian.research-and-discovery` | any | low/no approval |
| `openspec` | [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) | [X 2100625120691720385](https://x.com/i/status/2100625120691720385) | **hold** | Four-Signal 10/12. A third spec format beside ISA.md and GSD would split acceptance. | ceo, cto; `ceo.strategy-and-vision` | any | low/no approval |
| `spec-kit` | [github/spec-kit](https://github.com/github/spec-kit) | [X 2035687161471840641](https://x.com/i/status/2035687161471840641) | **hold** | Four-Signal 8/12. specs/ already follows its own numbered format. | ceo, cto; `ceo.strategy-and-vision` | any | low/no approval |
| `bmad-method` | [bmad-code-org/bmad-method](https://github.com/bmad-code-org/bmad-method) | [X 2103828182541734166](https://x.com/i/status/2103828182541734166) | **hold** | Four-Signal 9/12. Its persona org chart duplicates the seven Snow Gloves agents. | ceo, cto; `ceo.strategy-and-vision` | any | low/no approval |
| `portless` | [vercel-labs/portless](https://github.com/vercel-labs/portless) | [X 2090136598679560679](https://x.com/i/status/2090136598679560679) | **add** | Four-Signal 8/12. Fills the OAuth-redirect gap in connectors/g-stack/auth.py local testing. | cto; `cto.architecture-and-execution` | any | medium/approval |
| `xmcp` | [xdevplatform/xmcp](https://github.com/xdevplatform/xmcp) | [X 2040937372909531286](https://x.com/i/status/2040937372909531286) | **add** | Four-Signal 7/12. Cursor already ships plugin-x-x; do not build a second X bus. | dispatcher, librarian; `dispatcher.virality-and-distribution` | any | high/approval |
| `awesome-mcp-servers` | [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | [X 2096252768633995734](https://x.com/i/status/2096252768633995734) | **refuse** | Four-Signal 4/12. A link list is not an installable capability. | none | any | low/no approval |
| `claude-mem` | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | [X 2035312729427480840](https://x.com/i/status/2035312729427480840) | **refuse** | Four-Signal 7/12. Two memory stores would split truth. | librarian | claude, cursor | low/no approval |
| `open-seo` | [every-app/open-seo](https://github.com/every-app/open-seo) | [X 2093013941412852083](https://x.com/i/status/2093013941412852083) | **pointer** | Four-Signal 7/12. Method already adopted elsewhere; the pack also carries repo-maintenance skills unrelated to SEO. | interpreter, librarian; `interpreter.funnel-and-launch`, `librarian.knowledge-leadgen` | any | low/no approval |
| `executive-assistant` | [mgonto/executive-assistant-skills](https://github.com/mgonto/executive-assistant-skills) | [X 2029013122506223688](https://x.com/i/status/2029013122506223688) | **add** | Four-Signal 7/12. Fills the Chief of Staff inbox/calendar gap. Built for OpenClaw with personal accounts hard-coded; port, do not install as-is. | chief-of-staff; `chief-of-staff.people-ops` | openclaw | medium/approval |
| `chubbyskills` | [chubbyguan/chubbyskills](https://github.com/chubbyguan/chubbyskills) | [X 2103757085393490284](https://x.com/i/status/2103757085393490284) | **hold** | Four-Signal 6/12. Ingest overlaps scripts/ingest.py; only the China-platform readers are new. | librarian; `librarian.research-and-discovery` | any | low/no approval |
| `youtube-skills` | [ZeroPointRepo/youtube-skills](https://github.com/ZeroPointRepo/youtube-skills) | [X 2101399836587331901](https://x.com/i/status/2101399836587331901) | **refuse** | Four-Signal 5/12. Not copied into Field Theory for the same reason. | none | any | low/no approval |
| `buildwithclaude` | [davepoon/buildwithclaude](https://github.com/davepoon/buildwithclaude) | [X 2102000837027323970](https://x.com/i/status/2102000837027323970) | **refuse** | Four-Signal 3/12. Pick individual plugins as their own cards if ever needed. | none | claude | low/no approval |
| `antigravity-awesome-skills` | [sickn33/antigravity-awesome-skills](https://github.com/sickn33/antigravity-awesome-skills) | [X 2027336259040133499](https://x.com/i/status/2027336259040133499) | **refuse** | Four-Signal 3/12. Unreviewable surface area. | none | any | high/approval |
| `nous-hermes-agent` | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | [X 2100625120691720385](https://x.com/i/status/2100625120691720385) | **refuse** | Four-Signal 4/12. Name collision only; the Dispatcher bridge stays on the native bus. The `hermes` adapter targets the Nous runtime only when a founder picks it as a runtime. | dispatcher | hermes | low/no approval |
| `agent-reach` | [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) | [X 2101223518570488027](https://x.com/i/status/2101223518570488027) | **refuse** | Four-Signal 3/12. | none | any | high/approval |
| `graft` | [NanoNets/Graft](https://github.com/NanoNets/Graft) | [X 2091157554919280688](https://x.com/i/status/2091157554919280688) | **add** | Four-Signal 6/12. Fills codebase-context retrieval, which the tenant wiki does not cover. | cto, librarian; `cto.diagnostics-and-quality`, `librarian.research-and-discovery` | any | low/no approval |
| `brag` | [latent-spaces/brag](https://github.com/latent-spaces/brag) | [X 2103521939134550246](https://x.com/i/status/2103521939134550246) | **add** | Four-Signal 6/12. The crosswalk grouped it with Librarian/CTO; its job is launch assets, so it maps to the Interpreter funnel-and-launch hook. | interpreter; `interpreter.funnel-and-launch` | any | low/no approval |
| `archify` | [tt-a1i/archify](https://github.com/tt-a1i/archify) | [X 2102392223161786775](https://x.com/i/status/2102392223161786775) | **add** | Four-Signal 6/12. Fills the diagram gap for docs/architecture. | cto, librarian; `cto.architecture-and-execution` | any | low/no approval |
| `resume-skills` | [Paramchoudhary/ResumeSkills](https://github.com/Paramchoudhary/ResumeSkills) | [X 2101399836587331901](https://x.com/i/status/2101399836587331901) | **refuse** | Four-Signal 5/12. Duplicate of resume-enhancer, interview-prep-coach, and friends. | chief-of-staff | any | low/no approval |
| `career-ops` | [santifer/career-ops](https://github.com/santifer/career-ops) | [X 2101399836587331901](https://x.com/i/status/2101399836587331901) | **refuse** | Four-Signal 5/12. | chief-of-staff | any | low/no approval |

Changes from the crosswalk:

- **`brag`** moves to the Interpreter's `funnel-and-launch` hook. It makes launch videos; the crosswalk grouped it with Graft and archify under the Librarian and CTO.
- **`archify`** maps to `cto.architecture-and-execution` rather than diagnostics, because it produces diagrams.
- **"candidate"** rows became `add`, which means offered but not enabled. **"extract only"** and **"method already here"** became `pointer`. **"skip"** became `refuse`.

## 2. Field Theory taste packs (design, 2026-09-25, and tutor)

There are 27 pack directories. Sixteen of them are already covered by the section 1 cards (superpowers, agent-skills, bmad, open-seo, ResumeSkills, chubbyskills, OpenSpec, executive-assistant, claude-mem, spec-kit, brag, portless, Agent-Reach, career-ops, archify, and Graft). The remaining 11 are below.

| Card | Upstream | Citation | Disposition | Reason | Agent; hook | Runtimes | Risk |
|---|---|---|---|---|---|---|---|
| `tutor-skills` | [bevibing/tutor-skills](https://github.com/bevibing/tutor-skills) | [X 2102710818852982881](https://x.com/i/status/2102710818852982881) | **hold** | Unscored. Would sit beside professional-development-curator if a tenant needs training flows. | chief-of-staff, librarian | any | low/no approval |
| `taste-skill` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | [X 2033322376440549682](https://x.com/i/status/2033322376440549682) | **pointer** | Present locally as taste-skill / stitch-design-taste; point at it instead of copying. | cto, interpreter | any | low/no approval |
| `emil-skills` | [emilkowalski/skills](https://github.com/emilkowalski/skills) | [X 2075536512024994039](https://x.com/i/status/2075536512024994039) | **add** | Unscored, low risk. No Snow Gloves design hook exists; it would land under a future CTO frontend hook. | cto, interpreter | any | low/no approval |
| `layers` | [jamiemill/layers-skills](https://github.com/jamiemill/layers-skills) | [X 2075536512024994039](https://x.com/i/status/2075536512024994039) | **add** | Unscored, low risk. Fills product-strategy framing, which the CEO strategy hook lacks. | ceo, cto; `ceo.strategy-and-vision` | any | low/no approval |
| `platform-design` | [ehmo/platform-design-skills](https://github.com/ehmo/platform-design-skills) | [X 2102375290013933730](https://x.com/i/status/2102375290013933730) | **hold** | Unscored. Large reference; only useful with a native app in scope. | cto | any | low/no approval |
| `lazyweb` | [www.lazyweb.com](https://www.lazyweb.com/) | [X 2050579689249333722](https://x.com/i/status/2050579689249333722) | **hold** | Unscored. Do not pipe-install; the MCP endpoint is https://www.lazyweb.com/mcp/public. | interpreter, librarian | any | medium/approval |
| `frontend-design-pro` | [davepoon/buildwithclaude/tree/main/plugins/frontend-design-pro](https://github.com/davepoon/buildwithclaude/tree/main/plugins/frontend-design-pro) | [X 2102000837027323970](https://x.com/i/status/2102000837027323970) | **refuse** | The 2026-09-21 Hands harvest already refused it. | none | claude | low/no approval |
| `text-to-lottie` | [diffusionstudio/lottie](https://github.com/diffusionstudio/lottie) | [X 2064011863889788972](https://x.com/i/status/2064011863889788972) | **add** | Unscored, low risk. Fills motion assets for social and launch content. | interpreter; `interpreter.editorial-and-social` | claude, codex | low/no approval |
| `impeccable` | [impeccable.style](https://impeccable.style/) | [X 2075536512024994039](https://x.com/i/status/2075536512024994039) | **hold** | Unscored. Install only if the host gate is dropped. | cto, interpreter | any | low/no approval |
| `frontend-ui-engineering` | [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | [X 2096252768633995734](https://x.com/i/status/2096252768633995734) | **hold** | Extracted alone on 2026-09-25; same decision as agent-skills. | cto; `cto.architecture-and-execution` | any | low/no approval |
| `cinematic-scroll-prompt-kit` | [amirmushichge/cinematic-scroll-prompt-kit](https://github.com/amirmushichge/cinematic-scroll-prompt-kit) | [X 2081360473291628874](https://x.com/i/status/2081360473291628874) | **pointer** | Adjacent to scroll-world; no new organ. | interpreter | any | low/no approval |

## 3. Instagram saved harvest (Hands pointers)

The Hands organ logged these as candidates only. The Taste score is on a 1 to 5 scale.

| Card | Upstream | Citation | Disposition | Reason | Agent; hook | Runtimes | Risk |
|---|---|---|---|---|---|---|---|
| `threeui` | [MengTo/threeui](https://github.com/MengTo/threeui) | [IG DcWPxEhOepY](https://www.instagram.com/p/DcWPxEhOepY/) | **pointer** | Taste score 5. A frontend library, not an agent skill. | cto, interpreter | any | low/no approval |
| `godogen` | [htdt/godogen](https://github.com/htdt/godogen) | [IG Dcd84biuiDo](https://www.instagram.com/p/Dcd84biuiDo/) | **refuse** | Taste score 4, but the IG note says 'not an organ'. | none | any | low/no approval |
| `lenis` | [darkroomengineering/lenis](https://github.com/darkroomengineering/lenis) | [IG Da3O00jpo3R](https://www.instagram.com/p/Da3O00jpo3R/) | **pointer** | Taste score 5 (@fifbuilds). Library, not a skill. | cto | any | low/no approval |
| `gsap` | [greensock/GSAP](https://github.com/greensock/GSAP) | [IG Da3O00jpo3R](https://www.instagram.com/p/Da3O00jpo3R/) | **pointer** | Taste score 5. Use the host spoke. | cto | any | low/no approval |
| `vanta` | [tengbao/vanta](https://github.com/tengbao/vanta) | [IG Da3O00jpo3R](https://www.instagram.com/p/Da3O00jpo3R/) | **pointer** | Taste score 5. Library, not a skill. | cto | any | low/no approval |
| `react-bits` | [DavidHDev/react-bits](https://github.com/DavidHDev/react-bits) | [IG Da3O00jpo3R](https://www.instagram.com/p/Da3O00jpo3R/) | **pointer** | Taste score 5. Library, not a skill. | cto, interpreter | any | low/no approval |
| `claude-ads` | [AgriciDaniel/claude-ads](https://github.com/AgriciDaniel/claude-ads) | [IG DawBDyzkTf8](https://www.instagram.com/p/DawBDyzkTf8/) | **hold** | Only skill-shaped repo in the @hypertech dump. marketingskills ads/ad-creative cover the same ground. | dispatcher, interpreter; `interpreter.funnel-and-launch` | claude | high/approval |
| `openai-evals` | [openai/evals](https://github.com/openai/evals) | [IG Ct2Vp1Sto_q](https://www.instagram.com/p/Ct2Vp1Sto_q/) | **pointer** | The host quality-eval cluster is the working path. | cto, sentinel; `cto.diagnostics-and-quality` | any | low/no approval |
| `cobalt-tools` | [cobalt.tools](https://cobalt.tools/) | [IG DXrZxxhDmEM](https://www.instagram.com/p/DXrZxxhDmEM/) | **hold** | IG note: download utility, not a publisher. | librarian | any | medium/no approval |
| `scroll-world` | unresolved | [IG DavukqMiMAo](https://www.instagram.com/p/DavukqMiMAo/) | **hold** | Taste score 4. Four-Signal unscored; resolve the repo before any install. | cto, interpreter | claude, codex | low/no approval |
| `book-to-skill` | unresolved | [IG DbBcB4XujPM](https://www.instagram.com/p/DbBcB4XujPM/) | **hold** | Taste score 4 (@marc.kaz). A method for the Librarian, not an install. | librarian | any | low/no approval |
| `crucix` | [calesthio/Crucix](https://github.com/calesthio/Crucix) | [IG DWcdUBNDI50](https://www.instagram.com/p/DWcdUBNDI50/) | **refuse** | IG harvest marked it dropped. | none | any | low/no approval |

**Fence-skipped Instagram lists (no cards).** These are dump or bait posts. Per the IG harvest fence, their contents are never extracted into cards:

| Shortcode | What | Disposition |
|---|---|---|
| [DZ6iVvdDNt3](https://www.instagram.com/p/DZ6iVvdDNt3/) | @the_coding_wizard 10-repo dump (cal.com, plausible, Ghost, n8n, supabase, medusa, AppFlowy, coolify, listmonk, penpot) | refuse (dump class) |
| [DawBDyzkTf8](https://www.instagram.com/p/DawBDyzkTf8/) | @hypertech six-repo roundup (FinceptTerminal, Vibe-Trading, camofox-browser, hyperframes, open-generative-ai). Only claude-ads is carded | refuse (dump class) |
| [DZmfwsFkjsf](https://www.instagram.com/p/DZmfwsFkjsf/) | @blueviper.ai 500-projects list | refuse (dump class) |
| [DMvMvkvtKsB](https://www.instagram.com/p/DMvMvkvtKsB/), [DWtgbzLDgwm](https://www.instagram.com/p/DWtgbzLDgwm/), [DWywh1ljtqo](https://www.instagram.com/p/DWywh1ljtqo/), [DXhIODkDqq2](https://www.instagram.com/p/DXhIODkDqq2/), [DXjstfTDq5U](https://www.instagram.com/p/DXjstfTDq5U/), [Da3DJIGulrL](https://www.instagram.com/p/Da3DJIGulrL/) | eigent, onyx, the_well, rtk, docker-android, Ghost-Downloader-3 | skip-clone (no Snow Gloves hook) |
| Bait class (105 posts) | "comment LINKS / PROMPTS / SKILLS / CLAUDE / GD" funnels | refuse (Analyst `spotting-ai-slop`) |
| Design-tool URLs ([C2wwvZ4hdvx](https://www.instagram.com/p/C2wwvZ4hdvx/), [DFnOisLoz3W](https://www.instagram.com/p/DFnOisLoz3W/), [DJCOVxnCxRG](https://www.instagram.com/p/DJCOVxnCxRG/), …) | happyhues, huemint, cursify, motion freebies | Taste/Creative inbox only, not a catalog item |

## 4. founders-kit: one playbook card per category

Upstream: [avinash201199/founders-kit](https://github.com/avinash201199/founders-kit), read at commit `93cb1c8` on 2026-09-29. Citation: [X 2029874602621686154](https://x.com/i/status/2029874602621686154).

The index card `founders-kit` and all 33 category cards are `pointer`, low risk, and need no approval. They are reference lists, not tools, and the repo is not vendored; the reference clone stays on the founder Mac. Every card runs on any runtime. The upstream Product Directory and submission guide are not carded.

| Card | Section | Agent; hook |
|---|---|---|
| `fk-additional-learning-resources` | [Additional Learning Resources](https://github.com/avinash201199/founders-kit#additional-learning-resources) | librarian; `librarian.research-and-discovery` |
| `fk-affiliates-referrals` | [Affiliates & Referrals](https://github.com/avinash201199/founders-kit#affiliates--referrals) | dispatcher; `dispatcher.virality-and-distribution` |
| `fk-ai-tools` | [AI Tools](https://github.com/avinash201199/founders-kit#ai-tools) | cto; `cto.innovation-and-adapt` |
| `fk-analytics-data` | [Analytics & Data](https://github.com/avinash201199/founders-kit#analytics--data) | librarian; `librarian.research-and-discovery` |
| `fk-automation-backend` | [Automation & Backend](https://github.com/avinash201199/founders-kit#automation--backend) | cto; `cto.architecture-and-execution` |
| `fk-communities` | [Communities](https://github.com/avinash201199/founders-kit#communities) | dispatcher; `dispatcher.community-seeding` |
| `fk-company-building` | [Company Building](https://github.com/avinash201199/founders-kit#company-building) | ceo, chief-of-staff; `ceo.leadership-and-culture`, `ceo.strategy-and-vision` |
| `fk-content-seo` | [Content & SEO](https://github.com/avinash201199/founders-kit#content--seo) | interpreter, librarian; `librarian.knowledge-leadgen` |
| `fk-courses-videos` | [Courses & Videos](https://github.com/avinash201199/founders-kit#courses--videos) | librarian; `librarian.research-and-discovery` |
| `fk-crm-support` | [CRM & Support](https://github.com/avinash201199/founders-kit#crm--support) | chief-of-staff, dispatcher; `dispatcher.gtm-and-prospecting` |
| `fk-customer-development` | [Customer Development](https://github.com/avinash201199/founders-kit#customer-development) | ceo, librarian; `librarian.research-and-discovery` |
| `fk-design-tools` | [Design Tools](https://github.com/avinash201199/founders-kit#design-tools) | cto, interpreter; `interpreter.narrative-and-brand` |
| `fk-documentation` | [Documentation](https://github.com/avinash201199/founders-kit#documentation) | cto, librarian; `librarian.knowledge-leadgen` |
| `fk-email-newsletters` | [Email & Newsletters](https://github.com/avinash201199/founders-kit#email--newsletters) | interpreter; `interpreter.editorial-and-social` |
| `fk-fundraising` | [Fundraising](https://github.com/avinash201199/founders-kit#fundraising) | ceo, sentinel; `ceo.persuasion-and-image` |
| `fk-incubators-accelerators` | [Incubators & Accelerators](https://github.com/avinash201199/founders-kit#incubators--accelerators) | ceo; `ceo.strategy-and-vision` |
| `fk-inspiration-discovery` | [Inspiration & Discovery](https://github.com/avinash201199/founders-kit#inspiration--discovery) | interpreter, librarian; `librarian.research-and-discovery` |
| `fk-key-articles-essays` | [Key Articles & Essays](https://github.com/avinash201199/founders-kit#key-articles--essays) | ceo; `ceo.strategy-and-vision` |
| `fk-learning-knowledge` | [Learning & Knowledge](https://github.com/avinash201199/founders-kit#learning--knowledge) | ceo, librarian; `ceo.strategy-and-vision` |
| `fk-marketing-tools` | [Marketing Tools](https://github.com/avinash201199/founders-kit#marketing-tools) | dispatcher, interpreter; `interpreter.funnel-and-launch` |
| `fk-media-video` | [Media & Video](https://github.com/avinash201199/founders-kit#media-video) | interpreter; `interpreter.editorial-and-social` |
| `fk-miscellaneous-tools` | [Miscellaneous Tools](https://github.com/avinash201199/founders-kit#miscellaneous-tools) | chief-of-staff |
| `fk-monitoring-logging` | [Monitoring & Logging](https://github.com/avinash201199/founders-kit#monitoring--logging) | cto, sentinel; `cto.diagnostics-and-quality` |
| `fk-no-code-tools` | [No-Code Tools](https://github.com/avinash201199/founders-kit#no-code-tools) | cto; `cto.innovation-and-adapt` |
| `fk-payments` | [Payments](https://github.com/avinash201199/founders-kit#payments) | cto, sentinel; `sentinel.investment-and-financial-risk` |
| `fk-places-to-share-promote` | [Places to Share & Promote](https://github.com/avinash201199/founders-kit#places-to-share--promote) | dispatcher; `dispatcher.virality-and-distribution` |
| `fk-podcasts` | [Podcasts](https://github.com/avinash201199/founders-kit#podcasts) | librarian; `librarian.research-and-discovery` |
| `fk-startup-programs-credits` | [Startup Programs & Credits](https://github.com/avinash201199/founders-kit#startup-programs--credits) | ceo, sentinel; `ceo.strategy-and-vision` |
| `fk-stock-resources` | [Stock Resources](https://github.com/avinash201199/founders-kit#stock-resources) | interpreter; `interpreter.editorial-and-social` |
| `fk-team-management` | [Team Management](https://github.com/avinash201199/founders-kit#team-management) | chief-of-staff; `chief-of-staff.people-ops` |
| `fk-user-engagement` | [User Engagement](https://github.com/avinash201199/founders-kit#user-engagement) | interpreter; `interpreter.funnel-and-launch` |
| `fk-user-feedback` | [User Feedback](https://github.com/avinash201199/founders-kit#user-feedback) | librarian; `librarian.research-and-discovery` |
| `fk-website-hosting` | [Website & Hosting](https://github.com/avinash201199/founders-kit#website--hosting) | cto; `cto.architecture-and-execution` |

## 5. marketingskills: one card per skill

Upstream: [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills), read at commit `5b2c000` on 2026-09-29. It has 50 skills under `skills/`. Citation: [X 2035841006273548481](https://x.com/i/status/2035841006273548481).

All 50 cards are `add` and run on any runtime, because they are plain `SKILL.md` files. Where a card touches sending, spend, or public posting, it is marked `approval: yes`; Factor carried the whole pack as medium risk with approval. Each card installs exactly one skill; don't install the whole repo, because its `tools/` and `composio/` integrations are out of scope. The Interpreter gets 30 cards, the Dispatcher 15, and the Librarian 11. Some cards name more than one agent.

| Card | What it does | Agent; hook | Risk |
|---|---|---|---|
| [`ms-ab-testing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/ab-testing) | Plan and design A/B tests and a growth experiment program. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-ad-creative`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/ad-creative) | Generate and iterate ad headlines, descriptions, and variations. | interpreter; `interpreter.editorial-and-social` | low/no approval |
| [`ms-ads`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/ads) | Paid campaigns on Google, Meta, LinkedIn, X. Spend waits for approval. | dispatcher, interpreter; `interpreter.funnel-and-launch` | high/approval |
| [`ms-ai-seo`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/ai-seo) | Optimize content to be cited by LLMs and AI answer engines (AEO/GEO). | interpreter, librarian; `librarian.knowledge-leadgen` | low/no approval |
| [`ms-analytics`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/analytics) | Set up or audit tracking: GA4, events, UTMs, conversions. | librarian; `librarian.research-and-discovery` | low/no approval |
| [`ms-aso`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/aso) | Audit and optimize App Store and Google Play listings. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-attribution`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/attribution) | Choose and interpret attribution models; reconcile tool numbers. | librarian; `librarian.research-and-discovery` | low/no approval |
| [`ms-churn-prevention`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/churn-prevention) | Cancel flows, save offers, dunning, and retention. | interpreter; `interpreter.funnel-and-launch` | medium/no approval |
| [`ms-co-marketing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/co-marketing) | Find co-marketing partners and plan joint campaigns. | dispatcher; `dispatcher.virality-and-distribution` | low/no approval |
| [`ms-cold-email`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/cold-email) | B2B cold emails and follow-up sequences. Sending waits for approval. | dispatcher; `dispatcher.gtm-and-prospecting` | high/approval |
| [`ms-community-marketing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/community-marketing) | Community strategy for Discord, Slack, forums. Public posts wait for approval. | dispatcher; `dispatcher.community-seeding` | medium/approval |
| [`ms-competitor-profiling`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/competitor-profiling) | Research and profile competitors from their URLs. | librarian; `librarian.research-and-discovery` | low/no approval |
| [`ms-competitors`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/competitors) | Competitor comparison and alternative pages. | interpreter; `interpreter.narrative-and-brand` | low/no approval |
| [`ms-content-strategy`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/content-strategy) | Plan content strategy and topic coverage. | interpreter, librarian; `librarian.knowledge-leadgen` | low/no approval |
| [`ms-copy-editing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/copy-editing) | Edit, review, and refresh existing marketing copy. | interpreter; `interpreter.editorial-and-social` | low/no approval |
| [`ms-copywriting`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/copywriting) | Write or rewrite page copy: home, landing, pricing, feature. | interpreter; `interpreter.narrative-and-brand` | low/no approval |
| [`ms-cro`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/cro) | Raise conversion on marketing pages and forms. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-customer-research`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/customer-research) | Run and synthesize customer and ICP research. | librarian; `librarian.research-and-discovery` | low/no approval |
| [`ms-directory-submissions`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/directory-submissions) | Submit the product to startup/SaaS/AI directories. Each submission is public and waits for approval. | dispatcher; `dispatcher.virality-and-distribution` | medium/approval |
| [`ms-emails`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/emails) | Lifecycle and drip sequences. Sending waits for approval. | dispatcher, interpreter; `interpreter.funnel-and-launch` | medium/approval |
| [`ms-events`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/events) | Plan, sponsor, or speak at events for pipeline. Sponsorship spend waits for approval. | dispatcher; `dispatcher.virality-and-distribution` | medium/approval |
| [`ms-free-tools`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/free-tools) | Plan and build free tools as marketing (engineering as marketing). | cto, interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-image`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/image) | Create and optimize marketing images and brand assets. | interpreter; `interpreter.editorial-and-social` | low/no approval |
| [`ms-influencer-marketing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/influencer-marketing) | Creator and ambassador deals. Outreach and payments wait for approval. | dispatcher; `dispatcher.virality-and-distribution` | high/approval |
| [`ms-launch`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/launch) | Plan product launches, Product Hunt, feature announcements. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-lead-magnets`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/lead-magnets) | Plan and build lead magnets for email capture. | interpreter, librarian; `librarian.knowledge-leadgen` | low/no approval |
| [`ms-marketing-council`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/marketing-council) | Simulated board of legendary marketers for multi-perspective review. | ceo, interpreter; `interpreter.narrative-and-brand` | low/no approval |
| [`ms-marketing-ideas`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/marketing-ideas) | Marketing ideas and tactics for SaaS products. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-marketing-loops`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/marketing-loops) | Recurring agent-run marketing workflows. Each loop's first run waits for approval. | dispatcher; `dispatcher.virality-and-distribution` | medium/approval |
| [`ms-marketing-plan`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/marketing-plan) | Comprehensive marketing / GTM / AARRR plans. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-marketing-psychology`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/marketing-psychology) | Behavioral science and mental models applied to marketing. | interpreter; `interpreter.narrative-and-brand` | low/no approval |
| [`ms-offers`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/offers) | Design the offer: value framing, bonuses, guarantees, payment structure. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-onboarding`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/onboarding) | Post-signup onboarding and activation. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-paywalls`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/paywalls) | In-app paywalls, upgrade screens, feature gates. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-popups`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/popups) | Popups, modals, and slide-ins for conversion. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-pricing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/pricing) | Pricing, packaging, and monetization decisions. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-product-marketing`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/product-marketing) | Create the product-marketing context document other skills read. | interpreter; `interpreter.gtm-brief-synthesis`, `interpreter.narrative-and-brand` | low/no approval |
| [`ms-programmatic-seo`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/programmatic-seo) | SEO pages at scale from templates and data. Bulk publish waits for review. | librarian; `librarian.knowledge-leadgen` | medium/no approval |
| [`ms-prospecting`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/prospecting) | Find, qualify, and list prospects. Paid data pulls wait for approval. | dispatcher; `dispatcher.gtm-and-prospecting` | medium/approval |
| [`ms-public-relations`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/public-relations) | Earned media and journalist outreach. Pitches wait for approval. | dispatcher; `dispatcher.virality-and-distribution` | high/approval |
| [`ms-referrals`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/referrals) | Referral, affiliate, and word-of-mouth programs. | dispatcher; `dispatcher.virality-and-distribution` | low/no approval |
| [`ms-revops`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/revops) | Lead lifecycle, scoring, routing, and marketing-to-sales handoff. | chief-of-staff, dispatcher; `dispatcher.gtm-and-prospecting` | low/no approval |
| [`ms-sales-enablement`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/sales-enablement) | Sales decks, one-pagers, objection handling, demo scripts. | ceo, interpreter; `ceo.persuasion-and-image`, `interpreter.narrative-and-brand` | low/no approval |
| [`ms-schema`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/schema) | Schema markup and structured data (JSON-LD). | librarian; `librarian.knowledge-leadgen` | low/no approval |
| [`ms-seo-audit`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/seo-audit) | Technical and on-page SEO audits. | librarian; `librarian.knowledge-leadgen` | low/no approval |
| [`ms-signup`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/signup) | Signup and trial-activation flow optimization. | interpreter; `interpreter.funnel-and-launch` | low/no approval |
| [`ms-site-architecture`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/site-architecture) | Page hierarchy, navigation, URLs, and internal linking. | librarian; `librarian.knowledge-leadgen` | low/no approval |
| [`ms-sms`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/sms) | SMS/MMS marketing flows. Every send waits for approval. | dispatcher; `dispatcher.virality-and-distribution` | high/approval |
| [`ms-social`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/social) | Social content, scheduling, and listening. Posting waits for approval. | dispatcher, interpreter; `interpreter.editorial-and-social` | medium/approval |
| [`ms-video`](https://github.com/coreyhaines31/marketingskills/tree/main/skills/video) | AI and programmatic video production (Remotion, Hyperframes, HeyGen). | interpreter; `interpreter.editorial-and-social` | low/no approval |

## Gaps these catalogs fill

| Gap in the native graph (`workflows/skill-hooks.yaml`) | Filled by | Agent |
|---|---|---|
| Conversion work: CRO, signup, onboarding, paywalls, popups, A/B tests | `ms-cro`, `ms-signup`, `ms-onboarding`, `ms-paywalls`, `ms-popups`, `ms-ab-testing` | interpreter |
| Offer and pricing depth beyond `pricing-strategy-optimizer` | `ms-offers`, `ms-pricing`, `ms-churn-prevention` | interpreter |
| SEO and AI search (none native) | `ms-seo-audit`, `ms-ai-seo`, `ms-programmatic-seo`, `ms-schema`, `ms-site-architecture`, plus the `open-seo` method | librarian |
| Measurement: analytics and attribution (none native) | `ms-analytics`, `ms-attribution` | librarian |
| Outbound and PR (Explee covers search only) | `ms-cold-email`, `ms-prospecting`, `ms-public-relations`, `ms-influencer-marketing`, `ms-revops`, all approval-gated | dispatcher |
| Distribution beyond Reddit seeding | `ms-directory-submissions`, `ms-community-marketing`, `ms-co-marketing`, `ms-events`, `ms-marketing-loops`, `fk-places-to-share-promote` | dispatcher |
| Launch assets | `brag`, `text-to-lottie`, `ms-launch`, `ms-video` | interpreter |
| Founder playbooks: fundraising, accelerators, credits, company building | `fk-*` (33 cards) | ceo (and others per category) |
| Executive-assistant jobs: meeting prep, follow-ups, digest | `executive-assistant` (port it; don't install it as-is) | chief-of-staff |
| Code context and architecture diagrams | `graft`, `archify` | cto, librarian |
| OAuth redirect testing for G-Stack connectors | `portless` | cto |

**Gaps that remain.** No native hook exists yet for three areas:

- design and frontend (`emil-skills`, `layers`, `impeccable`, and the IG libraries)
- tutoring and learning (`tutor-skills`)
- evals (`openai-evals`)

The cards name agents but no hook. Adding a hook is its own change to `skill-hooks.yaml`.

## Founder pick list

These are the picks I recommend making first. None of them are enabled yet.

1. **Interpreter conversion set:** `ms-product-marketing` first, because the other marketingskills read its context doc. Then `ms-copywriting`, `ms-cro`, `ms-pricing`, and `ms-launch`. All are low risk.
2. **Librarian SEO set:** `ms-seo-audit`, `ms-ai-seo`, and `ms-customer-research`. All are low risk.
3. **Dispatcher outbound:** `ms-cold-email` and `ms-prospecting`. Both are approval-gated, and they pair with the existing `explee:explee-orchestrator` gtm hook.
4. **CEO playbooks:** `fk-fundraising`, `fk-startup-programs-credits`, and `fk-key-articles-essays`. These are pointers only.
5. **Chief of Staff:** `executive-assistant`. Port the meeting-prep and digest jobs, and keep sends approval-gated.
6. **CTO:** `archify` and `graft`, both low risk.
7. **Carried over from the harvest:** Addy Osmani spokes (pick one: `frontend-ui-engineering` or `planning-and-task-breakdown`), `portless` OAuth, and `brag`.

To apply a pick for a tenant, run `python3 scripts/onboard.py --tenant <slug> --enable <id,…>`. To route a pick by default, add it to `workflows/skill-hooks.yaml` in a separate reviewed change.

## Unresolved

- **scroll-world** ([IG DavukqMiMAo](https://www.instagram.com/p/DavukqMiMAo/)): the IG sidecar has no repo URL.
- **book-to-skill** ([IG DbBcB4XujPM](https://www.instagram.com/p/DbBcB4XujPM/)): the IG sidecar has no repo URL.
- **impeccable** and **lazyweb**: these are sites, not GitHub repos. The impeccable skill installs from `pbakaus/impeccable`, per the Field Theory INDEX.
- **Four-Signal scores**: the Field Theory design packs and IG items are still unscored. Their dispositions above are recommendations only.

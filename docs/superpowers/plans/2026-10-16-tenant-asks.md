# Tenant Asks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive founder asks from private tenant data, serve and answer them through the fleet coordinator, show them inside the town UI, and kick off one read-only research task per tenant.

**Architecture:** A pure Python deriver (`tenant_asks.py`) turns tenant files into asks with stable ids. A coordinator module (`fleet_asks.py`, installed like `fleet_capabilities.py`) lists asks per project and records founder answers in SQLite plus an append-only journal. The Vite UI fetches asks through the existing `/api/fleet` proxy with the Hermes board's operator token, broadcasts a `tenant-asks` document event, and the crew strip, brand markers and tenant card render from it.

**Tech Stack:** Python 3 stdlib + PyYAML (coordinator, scripts), pytest; TypeScript + Three.js + Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-10-16-tenant-asks-design.md`

## Global Constraints

- Ask kinds, exactly: `fact`, `decision`, `connect`, `website`, `brand`. Roles: `fact→librarian`, `decision→chief-of-staff`, `connect→dispatcher`, `website→interpreter`, `brand→interpreter`.
- Ask id = `sha256("<tenant>|<kind>|<key>")` hex, first 32 chars.
- Answer text ≤ 500 chars; ≤ 400 asks per tenant (truncate, oldest-file-order first kept); ask title ≤ 160 chars.
- Listing needs coordinator permission `read`; answering needs `approve`.
- Reject any ask title or answer that matches the sensitive filter (`token`, `password`, `secret`, `api key`, `sk-`, `ghp_`, `github_pat_`, `bearer`, `credential`). Ask titles are dropped; answers get a 400.
- Never write outside `tenants/<tenant>/asks/` under the data root, and never through a symlink.
- No private tenant names or facts in this repository; tests use the `heyzack` / `_demo` fixtures only.
- Workers stay read-only; kickoff tasks use `access: read`.

## Review Focus

1. A FILL line that changes wording yields a new id: the old answer must not attach to the new ask, and the old journal entry stays.
2. Answering an ask that is no longer derived (fact already filled) → 404, not a crash or a silent write.
3. A Yes/No ask answered with `{"value": ...}`, or a text ask answered with `{"accept": ...}` → 400.
4. Disconnecting the Hermes board must clear crew badges, marker counts and the tenant stack (no stale asks after the token is gone).
5. A tenant directory with no `context/`, a missing `MANIFEST.yaml` or invalid YAML yields only the asks it can derive, never an exception that hides other tenants.

---

### Task 1: Derive asks from tenant data

**Files:**
- Create: `scripts/lib/tenant_asks.py`
- Test: `tests/test_tenant_asks.py`

**Interfaces:**
- Produces:
  - `ASK_KINDS: tuple[str, ...]`, `ROLE_FOR_KIND: dict[str, str]`
  - `ask_id(tenant: str, kind: str, key: str) -> str`
  - `derive_asks(tenants_dir: Path, tenant: str, proposal: dict | None = None) -> list[dict]`. Each dict has exactly the keys `id, tenant, kind, role, title, source, answer_type, proposed`. `answer_type` is `"text"` or `"yes_no"`, and `proposed` is `str | None`.
  - `load_proposal(data_root: Path) -> dict | None`: reads `specs/006-editorial-steward-integration/portfolio-map-proposal.json` under the data root. Returns None if the file is missing or invalid, or larger than 512 KiB.

- [ ] **Step 1: Write the failing tests**

```python
def test_fill_lines_become_fact_asks(tmp_path):
    t = tmp_path / 'heyzack'; (t / 'context').mkdir(parents=True)
    (t / 'context/offer.md').write_text('# Offer\nFILL: the price.\n')
    (t / 'context/open-questions.md').write_text('- FILL: the price.\n')
    asks = derive_asks(tmp_path, 'heyzack')
    assert [(a['kind'], a['role'], a['title'], a['source'], a['answer_type']) for a in asks] == [
        ('fact', 'librarian', 'the price.', 'context/offer.md', 'text')]
    assert asks[0]['id'] == ask_id('heyzack', 'fact', 'context/offer.md|the price.')

def test_proposed_value_turns_fact_into_yes_no(tmp_path): ...
    # tenants/heyzack/asks/proposed.jsonl line {"ask_id": <id>, "proposed": "EUR 99"} -> answer_type 'yes_no', proposed 'EUR 99'

def test_decision_connect_website_brand(tmp_path): ...
    # proposal cross_brand_flows [{"id":"f1","status":"proposed_not_approved","participants":["heyzack"],"description":"X"}] -> one decision ask, key 'flow|f1'
    # sources.yaml {sources:[{id:'drive', type:'gdrive', admitted:false}]} -> connect ask key 'source|drive'
    # enabled.yaml module {id:'github-mcp', category:'mcp'} -> connect ask key 'module|github-mcp'
    # MANIFEST.yaml brand.domain 'FILL: confirm' -> website ask key 'domain'
    # no meristem source -> brand ask key 'meristem'; adding source id 'meristem-research' removes it

def test_sensitive_titles_dropped_and_caps(tmp_path): ...
    # 'FILL: the api key for X' is dropped; 450 FILL lines -> 400 asks; 200-char FILL -> title 160 chars

def test_broken_files_do_not_raise(tmp_path): ...
    # invalid YAML in MANIFEST/sources/enabled and missing context/ -> returns list (possibly empty), no exception
```

- [ ] **Step 2: Run** `python3 -m pytest -q tests/test_tenant_asks.py`. Expected: FAIL (`ModuleNotFoundError: lib.tenant_asks`).
- [ ] **Step 3: Implement `tenant_asks.py`.** Scan `context/*.md` sorted, skipping `open-questions.md`, for lines matching `^\s*-?\s*FILL:\s*(.+)$`. The key is `"<relpath>|<text>"`. Read YAML with `yaml.safe_load` inside try/except. Refuse symlinked files and files over 256 KiB. Read `asks/proposed.jsonl` (last record per `ask_id` wins; `proposed` ≤ 500 chars).
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `git add scripts/lib/tenant_asks.py tests/test_tenant_asks.py && git commit -m "Derive founder asks from tenant data"`

### Task 2: Coordinator asks API and answer journal

**Files:**
- Create: `scripts/lib/fleet_asks.py`
- Modify: `scripts/lib/fleet_coordinator.py`: install `fleet_asks` next to capabilities (around line 181) and add two routes beside the `/v1/approvals` routes (around line 1377).
- Test: `tests/test_fleet_asks.py` (reuse the `fleet` fixture from `test_fleet_coordinator.py` and the `approver` principal pattern from `test_fleet_capabilities.py`).

**Interfaces:**
- Consumes: `derive_asks`, `load_proposal` (Task 1); `paths.tenants_dir()`, `paths.data_root()`; `Capabilities.project(principal, project)` for the project → tenant mapping.
- Produces:
  - `install(coordinator)` creates `ask_answers(project TEXT, ask_id TEXT, tenant TEXT, kind TEXT, answer_json TEXT NOT NULL, answered REAL NOT NULL, answered_by TEXT NOT NULL, PRIMARY KEY(project, ask_id))`.
  - `Asks.list(owner, principal, project) -> {"asks": [public_ask]}`.
  - `Asks.answer(owner, principal, project, ask_id, body) -> {"ask": public_ask}`.
  - `public_ask` is the derived dict plus `project`, `status` (`"open"`/`"answered"`), `answer` (`{"value": str}` / `{"accept": bool}` / None), `answered`, `answered_by`.
  - Routes: `GET /v1/asks/<project>` and `POST /v1/asks/<project>/<32-hex>/answer`, where `<project>` matches `[a-z0-9][a-z0-9_-]{0,63}`.
  - Journal: one JSON line per answer appended to `<tenants_dir>/<tenant>/asks/answers.jsonl` with keys `answer_id, ask_id, project, tenant, kind, title, answer, answered, answered_by`, written only after the SQLite commit via an outbox table that is retried on the next answer, listing and coordinator start.

- [ ] **Step 1: Write the failing tests**

```python
def test_list_needs_read_and_project_scope(asks_ctx): ...   # founder sees asks; principal without project -> Rejected 403
def test_answer_requires_approve(asks_ctx): ...             # founder (no 'approve') -> 403; approver -> status 'answered'
def test_answer_shape_matches_type(asks_ctx): ...           # text ask + {"accept": True} -> 400; {"value": "x"*501} -> 400; {"value": "my token is abc"} -> 400; {} -> 400
def test_unknown_or_vanished_ask_404(asks_ctx): ...         # random id -> 404; fill the FILL line then answer old id -> 404
def test_answer_persisted_and_journaled(asks_ctx): ...      # second Coordinator on same data_root lists it answered; answers.jsonl has 1 line with answered_by 'approver'
def test_reanswer_updates_and_appends(asks_ctx): ...        # answering again with a new value -> latest shown; journal has 2 lines
def test_journal_refuses_symlink(asks_ctx): ...             # tenants/heyzack/asks is a symlink -> 503, nothing written outside
def test_http_routes(asks_ctx): ...                         # via the coordinator HTTP handler test helper: GET 200, POST answer 200, bad path 404
```

- [ ] **Step 2: Run** `python3 -m pytest -q tests/test_fleet_asks.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Raise errors through `fleet_capabilities.reject`. Answer under `self.c.transaction()`. Re-derive the asks at answer time to confirm the id still exists. Write the journal with `os.open(..., O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW)` after checking that the `asks/` directory resolves inside `tenants_dir`.
- [ ] **Step 4: Run** `python3 -m pytest -q tests/test_fleet_asks.py tests/test_fleet_coordinator.py tests/test_fleet_capabilities.py`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Serve and answer tenant asks through the coordinator"`

### Task 3: UI asks client, proxy route and ask stack

**Files:**
- Create: `apps/infra-block/src/tenant-asks.ts`, `apps/infra-block/src/tenant-asks.test.ts`
- Modify: `apps/infra-block/src/fleet-proxy.ts`: allow `GET /api/fleet/asks/<project>` and `POST /api/fleet/asks/<project>/<32hex>/answer`. Update `fleet-proxy.test.ts`.
- Modify: `apps/infra-block/src/fleet-tasks.ts`: add the `FleetClient.asks` and `FleetClient.answerAsk` methods, using the existing request helper, and add the two ask paths to its own client-side GET/POST path allowlist (near line 127).
- Modify: `apps/infra-block/src/ops.css`: add the `.oc-asks*` styles in the cream-panel / orange-button look.

**Interfaces:**
- Produces:
  - `export type AskKind = 'fact'|'decision'|'connect'|'website'|'brand'`
  - `export interface TenantAsk {id: string; project: string; tenant: string; kind: AskKind; role: ResidentSlug; title: string; source: string; answerType: 'text'|'yes_no'; proposed: string|null; status: 'open'|'answered'; answer: {value: string}|{accept: boolean}|null}`
  - `parseAsks(raw: unknown, project: string): TenantAsk[]` (throws on any malformed field; camelCases `answer_type`)
  - `summarizeAsks(asks: TenantAsk[]): {byTenant: Record<string, number>; byRole: Partial<Record<ResidentSlug, number>>}`, counting open asks only
  - `renderAskStack(asks: TenantAsk[], onAnswer: (ask: TenantAsk, answer: {value: string}|{accept: boolean}) => Promise<void>): HTMLElement`
  - `FleetClient.asks(project: string): Promise<TenantAsk[]>`; `FleetClient.answerAsk(project: string, id: string, answer: {value: string}|{accept: boolean}): Promise<TenantAsk>`
  - `startAskSync(client: FleetClient, projects: string[], emit: (asks: TenantAsk[]|null) => void, intervalMs = 60000): () => void`. The returned stop function emits `null`.

- [ ] **Step 1: Write failing vitest tests:** `parseAsks` rejects a wrong project, unknown kind, or `role` outside RESIDENTS. `summarizeAsks` ignores answered asks. `renderAskStack`: a yes_no ask shows the proposed value plus Yes and No buttons, and clicking Yes calls `onAnswer(ask, {accept: true})`. A text ask shows an input with `maxLength` 500, and an empty submit doesn't call `onAnswer`. Proxy: both new routes are allowed, and `/api/fleet/asks/x/notanid/answer` is rejected. `startAskSync` stop emits `null`.
- [ ] **Step 2: Run** `npx --prefix apps/infra-block vitest run tenant-asks fleet-proxy`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use `textContent` only, never `innerHTML`. On rejection, the stack disables the buttons and shows the coordinator's message.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Add tenant asks client and ask stack"`

### Task 4: Asks inside the town

**Files:**
- Modify: `apps/infra-block/src/fleet-tasks.ts`: once the board connects and the context loads, call `startAskSync(client, context.projects.map(p => p.id), emit)`. The emit dispatches `document.dispatchEvent(new CustomEvent('tenant-asks', {detail}))`. Stop the sync on disconnect, and on `pause(true)`.
- Modify: `apps/infra-block/src/home.ts`: listen for `tenant-asks`. Crew portraits show a badge with `byRole[slug]`, and the label reads `"<n> asks waiting"` when n > 0. Selecting a resident opens `renderAskStack` filtered to that role in the existing resident detail panel.
- Modify: `apps/infra-block/src/brand-atlas.ts`: add `BrandMarkersHandle.setAskCounts(counts: Record<string, number>)` (a canvas-texture sprite above each marker; no sprite for 0), and show the count beside each brand in `mountBrandAtlas`.
- Modify: `apps/infra-block/src/world.ts`, `apps/infra-block/src/main.ts`: forward `tenant-asks` to `canvasMount` as `brand-ask-counts` (detail `Record<string, number>`), then on to `brandMarkers.setAskCounts`.
- Modify: `apps/infra-block/src/ops.ts`: `openTenant(slug)` adds a "Waiting on you" section that renders `renderAskStack` for that tenant's asks (latest event), or "Connect the Hermes board to see asks" when none have been received.
- Test: extend `home`/`brand-atlas`/`ops` tests where they exist; otherwise add `apps/infra-block/src/tenant-asks-town.test.ts`.

**Interfaces:**
- Consumes: Task 3 exports; the `tenant-asks` event detail `TenantAsk[]|null`.

- [ ] **Step 1: Write failing tests:**
  - dispatching `tenant-asks` with two open librarian asks makes the Librarian badge read `2`;
  - dispatching `null` clears every badge (Review Focus 4);
  - `setAskCounts({heyzack: 3})` adds exactly one sprite, and `setAskCounts({})` removes it;
  - `openTenant('heyzack')` after the event lists that tenant's asks only.
- [ ] **Step 2: Run** `npx --prefix apps/infra-block vitest run`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the wiring above.
- [ ] **Step 4: Run** `npx --prefix apps/infra-block vitest run && npm --prefix apps/infra-block run build`. Expected: all tests pass and the build succeeds.
- [ ] **Step 5: Verify in the running app:**
  - start `infra-block`, the coordinator and the cockpit API locally against a temp data root seeded with the `heyzack` fixture;
  - connect the Hermes board;
  - confirm the crew badge, the marker sprite and the tenant section appear;
  - answer one ask and confirm the badge decrements.
- [ ] **Step 6: Commit** `git commit -m "Show tenant asks in the town, crew strip and tenant card"`

### Task 5: Admission, kickoff and proposal import scripts

**Files:**
- Create: `scripts/fleet_admit_tenants.py`, `scripts/fleet_kickoff.py`, `scripts/fleet_asks_import.py`
- Test: `tests/test_fleet_kickoff.py`

**Interfaces:**
- Produces:
  - `admit(config: dict, tenants: list[str], organization: str, principal: str, workers: list[str], root: str | None = None) -> dict`. It returns a new config where each tenant is a project `{tenant, organization, runtimes: ['codex']}` keyed by the tenant slug (an existing project already mapped to that tenant is left untouched). The new project ids are appended to `principals[principal].projects` and to each listed `workers[w].projects`. It never sets `write`, `fanout` or `write_projects`. A `root` (absolute Git checkout) is required when any listed worker is local, because the coordinator refuses projects served by local workers without one. CLI: `--config PATH --tenants a,b --organization ORG --principal NAME --workers w1,w2 [--root PATH] [--write]`. The default prints a JSON diff.
  - `kickoff_brief(tenant: str, asks: list[dict]) -> str`. A ≤ 16000-char brief listing up to 40 open `fact` asks as `- <id>: <title> (<source>)`. It tells the worker to propose values only from the tenant's context, public sources and Meristem outputs. It requires a final JSON array of `{"ask_id","proposed","evidence"}` and says to omit any ask with no evidence. CLI `fleet_kickoff.py --coordinator URL --token-file PATH --projects a,b [--submit]` posts `{project, title: "Kickoff research: <tenant>", brief, category: "development", access: "read", idempotency_key: "kickoff-<project>-2026-10-16"}`.
  - `import_proposals(tenants_dir: Path, tenant: str, artifact_text: str, known_ids: set[str]) -> int`. It takes the last JSON array in the artifact, keeps entries whose `ask_id` is in `known_ids` and whose `proposed` is ≤ 500 chars and passes the sensitive filter, appends them to `asks/proposed.jsonl`, and returns the count. CLI `fleet_asks_import.py --coordinator URL --token-file PATH --task ID`.

- [ ] **Step 1: Write failing tests:**
  - `admit` is idempotent, never adds write grants, and keeps an existing project that maps to `heyzack`;
  - `kickoff_brief` caps at 40 asks and 16000 chars;
  - `import_proposals` ignores unknown ids, sensitive values and malformed JSON, and the count matches the lines written.
- [ ] **Step 2: Run** `python3 -m pytest -q tests/test_fleet_kickoff.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** The token is read from a file only, never from argv or the environment. HTTP uses `urllib.request` with a 30 s timeout.
- [ ] **Step 4: Run** `python3 -m pytest -q tests/`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Admit tenant projects and kick off read-only research"`

### Task 6: Deploy to Coding 01 and start the work (founder go-ahead required)

Live change on the physical mini. Nothing here runs without the founder's explicit yes in chat.

- [ ] **Step 1:** Push `feat/tenant-asks`, open a PR, and merge after review.
- [ ] **Step 2:** On Coding 01, move the platform checkout used by the coordinator, cockpit and UI services to the merged `main`, then rebuild the UI (`npm --prefix apps/infra-block run build`).
- [ ] **Step 3:** Run `fleet_admit_tenants.py` against the live `coordinator.json` without `--write` and show the diff to the founder. After a yes, run it with `--write`, then restart the coordinator service.
- [ ] **Step 4:** Verify `GET /v1/asks/<project>` returns asks for every admitted tenant. Open fleet.hey-zack.fr and connect the board: crew badges and brand marker counts must show.
- [ ] **Step 5:** Run `fleet_kickoff.py` without `--submit` and show the briefs. After a yes, run it with `--submit`.
- [ ] **Step 6:** As kickoff tasks succeed, run `fleet_asks_import.py` for each. The proposals then appear as Yes/No asks in the town.

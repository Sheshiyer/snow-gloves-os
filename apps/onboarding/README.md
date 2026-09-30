# Snow Gloves Onboarding (Tauri v2)

Native desktop wrapper around repo scripts (`doctor.sh`, `tenant_new.sh`, `make smoke`). Identifier `com.tryambakam.snowgloves.onboarding`, version **0.2.1**. This is **not** the plan-mode interview (`make onboard-prompt`); that still happens in Cursor or Claude after the wizard (or instead of it). See [`docs/MAC-MINI-SETUP.md`](../../docs/MAC-MINI-SETUP.md) for using the product on a new Mini.

v0.1.x OTA cannot update to 0.2.0 (new bundle id). New machines install a new DMG from GitHub Releases, or run from this repo as below.

## Prereqs (this Mac, or a blank Mini if you insist on building)

| Need | Why | Mini first-hour? |
|---|---|---|
| Node 20+ | Vite + `@tauri-apps/cli` | Only if you run `app-dev` / `app-build`. Product path needs Node for `paperclipai`, not for Tauri. |
| Rust stable (`rustup`) | `src-tauri` crate | No for product use. |
| Xcode or Command Line Tools (`xcode-select --install`) | macOS WebView / codesign toolchain | No for product use. |
| Developer ID `Thoughtseed Private Limited (BS6SZR4929)` | Signed `make app-build` | No. Unsigned local `.app` is Gatekeeper-hostile; use a notarized Release DMG on a Mini. |

Confirm the emulate path without opening a window:

```bash
cd apps/onboarding && npx tauri --version   # expect 2.x
cargo --version
cd src-tauri && cargo check                 # enough to say the Rust side compiles
```

Do **not** leave `npm run tauri dev` running in the background in agent sessions (it opens a GUI and holds the Vite port).

## Emulate on this Mac

From the **repo root**:

```bash
make app-install    # cd apps/onboarding && npm install
make app-dev        # cd apps/onboarding && npm run tauri dev
```

Equivalent:

```bash
cd apps/onboarding
npm install
npm run tauri dev
```

That starts Vite on **http://localhost:5180** (`tauri.conf.json` → `build.devUrl`) then a native window **Snow Gloves OS · Onboarding** (920×720). The Rust side resolves repo root as `apps/onboarding/src-tauri` → three parents up, then runs `scripts/doctor.sh` and friends **in this clone**.

Wizard steps: welcome → doctor (`make doctor` markers) → tenant (`tenant_new.sh`) → optional Paperclip UUID (`paperclip.tn.local` is a placeholder — leave empty) → source paths → provision → optional streamed `make smoke`. **Modules** tab reads `catalog/modules.json` + tenant `enabled.yaml`. Footer still shows a stale “v0.1.4” string; ignore it.

## Unsigned vs signed release

| Command | What you get | Signing | Use |
|---|---|---|---|
| `make app-dev` / `npm run tauri dev` | Dev app, hot reload | None | Emulate the wizard **on this Mac**. |
| `make app-build` / `npm run tauri build` | `src-tauri/target/release/bundle/{macos,dmg,…}` | Uses `bundle.macOS.signingIdentity` in `tauri.conf.json` (`Developer ID Application: Thoughtseed Private Limited (BS6SZR4929)`). **Fails** if that identity is not in the keychain. **Not notarized.** | Local signed binary for you; other Macs may still Gatekeeper-block until notarized. |
| Same build with identity `-` | Unsigned `.app` / `.dmg` | Explicit skip | Debugging only. Do not ship to the Mini. |
| GitHub `release.yml` | Notarized universal DMG + updater `latest.json` | CI cert + `notarytool` | What a Mini should install if using the GUI. |

Fully signed local build (still no notarization) — from [`docs/RELEASING.md`](../../docs/RELEASING.md):

```bash
cd apps/onboarding
export TAURI_SIGNING_PRIVATE_KEY=$(cat ~/.tauri/snowgloves-updater.key)
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
export APPLE_SIGNING_IDENTITY="Developer ID Application: Thoughtseed Private Limited (BS6SZR4929)"
npx tauri build
```

Skip Apple signing when the cert is absent (Tauri treats `-` as unsigned):

```bash
cd apps/onboarding
npx tauri build --config '{"bundle":{"macOS":{"signingIdentity":"-"}}}'
```

## What it does
1. **Preflight** — invokes `scripts/doctor.sh`, parses ✓ / ! / ✗ markers, renders a checklist.
2. **Tenant** — collects business name + slug; shells out to `scripts/tenant_new.sh <slug> "<name>"`.
3. **Paperclip bind** — patches `tenants/<slug>/MANIFEST.yaml` `paperclip.company_id` in place.
4. **Sources** — writes `tenants/<slug>/sources.yaml` with path entries.
5. **Smoke** — runs `make smoke` and streams stdout/stderr line-by-line via a Tauri event (`smoke-line`).

## IPC surface
| Command | Args | Returns |
|---|---|---|
| `run_doctor` | – | `{ok,total,passed,failed,checks[],raw}` |
| `create_tenant` | `{slug,business,companyId?,sources[]}` | `{path,sources_added,company_bound}` |
| `list_tenants` | – | `string[]` |
| `run_smoke` | – | streams `smoke-line` events; resolves on exit |
| `open_repo` | – | opens repo root in Finder/Explorer |
| `quit_app` | – | exits app |

## Capabilities
`core:default` + window/event/shell/dialog. No filesystem capability needed because all writes go through the Rust commands, not the JS frontend.

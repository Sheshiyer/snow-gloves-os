# Snow Gloves Onboarding (Tauri v2)

Native desktop wrapper for the `bash scripts/onboarding.sh` flow.

## Prereqs
- Rust toolchain (`rustup default stable`)
- Node 20+
- macOS: Xcode CLT (`xcode-select --install`)

## Develop
```bash
cd apps/onboarding
npm install
npm run tauri dev
```

## Build a release binary
```bash
npm run tauri build
# → src-tauri/target/release/bundle/{macos,dmg,...}
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

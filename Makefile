SHELL := /bin/bash
PYTHON ?= python3
HERMES_PORT ?= 4100
# Fixture targets (smoke, walk) run on the public `_demo` fixture in this checkout, never on
# the private data checkout, so they drop SNOWGLOVES_DATA (see scripts/lib/paths.py).
FIXTURE_ENV := env -u SNOWGLOVES_DATA

.PHONY: help install onboard onboard-prompt hermes smoke embed sentinel kill-hermes clean doctor test tenant-new approvals replay catalog catalog-check legacy-check site upgrade graph-upgrade walk tui app-install app-dev app-build

help:
	@echo "Snow Gloves OS — make targets"
	@echo "  make doctor                # pre-flight diagnostic"
	@echo "  make install               # bootstrap deps; prints onboard steps (not live)"
	@echo "  make onboard               # interactive tenant + sources prompt (legacy)"
	@echo "  make onboard-prompt R=<rt> # print the plan-mode interview prompt for a runtime"
	@echo "  make catalog               # rebuild catalog/modules.json"
	@echo "  make catalog-check         # fail if catalog/modules.json is stale"
	@echo "  make legacy-check          # fail if pre-Hermes bus names remain (skips .bak-*)"
	@echo "  make site                  # build the static Pages site"
	@echo "  make release-dry V=x.y.z   # preview a platform version bump"
	@echo "  make release V=x.y.z       # bump, commit, tag vX.Y.Z (no push)"
	@echo "  make release-push V=x.y.z  # push HEAD + tag vX.Y.Z"
	@echo "  make upgrade [T=<slug>]    # dry-run tenant platform migrations (WRITE=1 to apply)"
	@echo "  make walk                  # machine-check the CoS graph (produce/check/correct)"
	@echo "  make tui                   # rich onboarding TUI (agent|TUI toggle; agents: --headless)"
	@echo "  make graph-upgrade         # learning-edge dry-run (WRITE=1 applies constraints; hooks need approval)"
	@echo "  make tenant-new T=<slug>   # scaffold a new tenant"
	@echo "  make hermes                # run Hermes listener (foreground)"
	@echo "  make smoke                 # full e2e smoke"
	@echo "  make embed T=<tenant>      # NVIDIA embed worker (QUIET=1 for cron)"
	@echo "  make sentinel              # daily drift sweep"
	@echo "  make approvals T=<tenant>  # list pending approval tickets"
	@echo "  make replay N=5            # replay last N events through current hooks"
	@echo "  make test                  # pytest"
	@echo "  make mods-check            # validate + test every Claude Code mod in mods/, then the mod rules"
	@echo "  make mods-dev [T=<tenant>] # start claude with every mod in mods/ loaded from its folder"
	@echo "  make kill-hermes           # free port $(HERMES_PORT)"
	@echo "  make app-install           # npm install for the Tauri onboarding app"
	@echo "  make app-dev               # tauri dev (GUI; do not leave running in agents)"
	@echo "  make app-build             # tauri release bundle (needs signing identity)"
	@echo "  make fleet-doctor [W=<wing>]            # is this mini wired as its wing says (fleet.yaml; \$$SNOWGLOVES_DATA)"
	@echo "  make fleet-render W=<wing> T=<tenant> R=<rt>  # render brand x wing x runtime (WRITE=1 applies)"
	@echo "  make fleet-enable W=<wing> T=<tenant>|all     # enable a brand on a wing"
	@echo "  make fleet-connect W=<wing>             # open a shell on a wing over Tailscale"
	@echo "  make fleet-kit-export                   # export the gateway kit from the authoring seat"
	@echo "  make fleet-remote-access W=<wing>       # ARD / Screen Sharing / SSH plan (dry-run)"

doctor:
	bash scripts/doctor.sh

install:
	bash scripts/install.sh

onboard:
	bash scripts/onboarding.sh

onboard-prompt:
	@if [ -z "$(R)" ]; then echo "usage: make onboard-prompt R=<runtime>"; exit 1; fi
	$(PYTHON) scripts/onboard.py --prompt $(R)

catalog:
	$(PYTHON) scripts/build_catalog.py

catalog-check:
	$(PYTHON) scripts/build_catalog.py --check

legacy-check:
	@! grep -rIl -e 'sg[_]bus' -e 'SG[ ]Bus' . --exclude-dir=.git --exclude-dir='.bak-*' \
	  --exclude-dir=node_modules --exclude-dir=target || (echo "legacy bus names found (above)"; exit 1)
	@echo "legacy-check: clean"

site:
	cd apps/onboarding && npm run build:site

upgrade:
	$(PYTHON) scripts/upgrade.py $(if $(T),--tenant $(T),) $(if $(WRITE),--write,)

walk:
	$(FIXTURE_ENV) $(PYTHON) scripts/graph_walk.py

tui:
	$(PYTHON) scripts/tui_onboard.py $(ARGS)

graph-upgrade:
	$(PYTHON) scripts/graph_upgrade.py $(if $(T),--tenant $(T),) $(if $(WALK),--walk $(WALK),) $(if $(WRITE),--write,)

tenant-new:
	@if [ -z "$(T)" ]; then echo "usage: make tenant-new T=<slug> [N=\"Business Name\"]"; exit 1; fi
	bash scripts/tenant_new.sh $(T) $(N)

hermes:
	$(PYTHON) scripts/hermes.py

kill-hermes:
	-@lsof -ti tcp:$(HERMES_PORT) | xargs kill -9 2>/dev/null; true

smoke: kill-hermes
	@echo "==> [1/5] starting Hermes in background"
	@$(FIXTURE_ENV) $(PYTHON) scripts/hermes.py & echo $$! > .hermes.pid; sleep 0.5
	@echo "==> [2/5] firing e2e test event"
	@curl -sS -X POST http://127.0.0.1:$(HERMES_PORT)/test/e2e -H 'Content-Type: application/json' -d '{}' > .e2e.json
	@cat .e2e.json | $(PYTHON) -m json.tool
	@echo "==> [3/5] bridging decision to Paperclip (dry-run)"
	@cat .e2e.json | $(FIXTURE_ENV) $(PYTHON) scripts/paperclip_bridge.py --tenant _demo --dry-run
	@echo "==> [4/5] running embed worker on _demo (stub backend)"
	@mkdir -p tenants/_demo
	@printf "Snow Gloves OS uses NVIDIA embeddings to interpret tenant wikis.\n" > /tmp/sg_sample.md
	@$(PYTHON) -c "import json,pathlib; pathlib.Path('tenants/_demo/ingest-plan.json').write_text(json.dumps({'tenant':'_demo','files':[{'path':'/tmp/sg_sample.md','size':128}]}))"
	@SNOWGLOVES_EMBED_BACKEND=stub $(FIXTURE_ENV) $(PYTHON) scripts/embed_worker.py _demo
	@echo "==> [5/5] sentinel sweep"
	@$(FIXTURE_ENV) $(PYTHON) scripts/sentinel_sweep.py
	@echo "==> stopping Hermes"
	@kill $$(cat .hermes.pid) 2>/dev/null; rm -f .hermes.pid .e2e.json
	@echo "==> smoke complete ✅"

embed:
	@if [ -z "$(T)" ]; then echo "usage: make embed T=<tenant>"; exit 1; fi
	$(PYTHON) scripts/embed_worker.py $(T) $(if $(QUIET),--quiet,)

sentinel:
	$(PYTHON) scripts/sentinel_sweep.py

approvals:
	@if [ -z "$(T)" ]; then echo "usage: make approvals T=<tenant>"; exit 1; fi
	$(PYTHON) scripts/approvals.py list --tenant $(T)

replay:
	$(PYTHON) scripts/replay.py --last $(if $(N),$(N),5)

test:
	$(PYTHON) -m pytest -q tests/

# ---- Claude Code mods (mods/; see docs/mods.md) ----
.PHONY: mods-check mods-dev
MOD_DIRS := $(sort $(dir $(wildcard mods/*/.claude-plugin/plugin.json)))

mods-check:
	@command -v claude >/dev/null || { echo "mods-check needs the claude CLI (v2.1.287+)"; exit 2; }
	claude plugin validate --strict mods
	@set -e; for d in $(MOD_DIRS); do d=$${d%/.claude-plugin/}; \
	  echo "== $$d"; claude plugin validate --strict $$d; (cd $$d && claude plugin test); done
	$(PYTHON) scripts/check_mod_invariants.py --require-claude

mods-dev:
	$(if $(T),SNOWGLOVES_TENANT=$(T)) claude $(foreach d,$(MOD_DIRS),--plugin-dir $(patsubst %/.claude-plugin/,%,$(d)))

clean:
	rm -f .hermes.pid .e2e.json

# ---- fleet (three Mac minis by wing; see docs/fleet/README.md) ----
.PHONY: fleet-doctor fleet-render fleet-enable fleet-connect fleet-kit-export fleet-remote-access
fleet-doctor:
	$(PYTHON) scripts/fleet/doctor.py $(if $(W),--wing $(W),)

fleet-render:
	@if [ -z "$(W)" ] || [ -z "$(T)" ] || [ -z "$(R)" ]; then echo "usage: make fleet-render W=<wing> T=<tenant> R=<runtime> [WRITE=1]"; exit 1; fi
	$(PYTHON) scripts/fleet/node_profile.py render --tenant $(T) --node $(W) --runtime $(R) $(if $(WRITE),--write,)

fleet-enable:
	@if [ -z "$(W)" ] || [ -z "$(T)" ]; then echo "usage: make fleet-enable W=<wing> T=<tenant>|all"; exit 1; fi
	$(PYTHON) scripts/fleet/node_profile.py enable --node $(W) $(if $(filter all,$(T)),--all-tenants,--tenant $(T))

fleet-connect:
	@if [ -z "$(W)" ]; then echo "usage: make fleet-connect W=<wing>"; exit 1; fi
	bash scripts/fleet/connect.sh $(W)

fleet-kit-export:
	bash scripts/fleet/gateway_kit.sh export

fleet-remote-access:
	@if [ -z "$(W)" ]; then echo "usage: make fleet-remote-access W=<wing>"; exit 1; fi
	bash scripts/fleet/remote_access.sh --wing $(W)


# ---- Onboarding app (Tauri v2) ----
app-install:
	cd apps/onboarding && npm install

app-dev:
	cd apps/onboarding && npm run tauri dev

app-build:
	cd apps/onboarding && npm run tauri build

# ---- release ----
.PHONY: release release-dry release-check release-push release-tag release-dispatch
release-dry:
	@test -n "$(V)" || (echo "usage: make release-dry V=0.2.0"; exit 1)
	$(PYTHON) scripts/release.py $(V) --dry-run

release:
	@test -n "$(V)" || (echo "usage: make release V=0.2.0"; exit 1)
	$(PYTHON) scripts/release.py $(V) --commit --tag

release-check:
	$(PYTHON) scripts/release.py --check

release-push:
	@test -n "$(V)" || (echo "usage: make release-push V=0.2.0"; exit 1)
	git push origin HEAD v$(V)

release-tag:
	@test -n "$(V)" || (echo "usage: make release-tag V=0.1.0"; exit 1)
	@git tag -a v$(V) -m "release: v$(V)" && git push origin v$(V)
	@echo "→ pushed tag v$(V); GitHub Actions is retired; no installers or updater manifest are published by this tag push"

release-dispatch:
	@test -n "$(V)" || (echo "usage: make release-dispatch V=0.1.0"; exit 1)
	@echo 'GitHub Actions release dispatch is retired. Build locally with make app-build; review signing, platform assets, and updater metadata before separate publication.' >&2
	@exit 2

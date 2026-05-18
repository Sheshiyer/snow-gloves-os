SHELL := /bin/bash
PYTHON ?= python3
HERMES_PORT ?= 4100

.PHONY: help install onboard hermes smoke embed sentinel kill-hermes clean

help:
	@echo "Snow Gloves OS — make targets"
	@echo "  make install     # bootstrap (paperclipai + python deps)"
	@echo "  make onboard     # interactive tenant onboarding"
	@echo "  make hermes      # run Hermes listener (foreground)"
	@echo "  make smoke       # full end-to-end smoke (hermes -> e2e -> bridge -> embed -> sentinel)"
	@echo "  make embed T=<tenant>     # run NVIDIA embed worker (stub if no key)"
	@echo "  make sentinel    # run daily drift sweep"
	@echo "  make kill-hermes # free port $(HERMES_PORT)"

install:
	bash scripts/install.sh

onboard:
	bash scripts/onboarding.sh

hermes:
	$(PYTHON) scripts/hermes.py

kill-hermes:
	-@lsof -ti tcp:$(HERMES_PORT) | xargs kill -9 2>/dev/null; true

smoke: kill-hermes
	@echo "==> [1/5] starting Hermes in background"
	@$(PYTHON) scripts/hermes.py & echo $$! > .hermes.pid; sleep 0.5
	@echo "==> [2/5] firing e2e test event"
	@curl -sS -X POST http://127.0.0.1:$(HERMES_PORT)/test/e2e -H 'Content-Type: application/json' -d '{}' > .e2e.json
	@cat .e2e.json | $(PYTHON) -m json.tool
	@echo "==> [3/5] bridging decision to Paperclip (dry-run)"
	@cat .e2e.json | $(PYTHON) scripts/paperclip_bridge.py --tenant _demo --dry-run
	@echo "==> [4/5] running embed worker on _demo (stub backend)"
	@mkdir -p tenants/_demo
	@printf "Snow Gloves OS uses NVIDIA embeddings to interpret tenant wikis.\nHermes routes events to the right agent skill via Chief of Staff.\n" > /tmp/sg_sample.md
	@$(PYTHON) -c "import json,pathlib; pathlib.Path('tenants/_demo/ingest-plan.json').write_text(json.dumps({'tenant':'_demo','files':[{'path':'/tmp/sg_sample.md','size':128}]}))"
	@SNOWGLOVES_EMBED_BACKEND=stub $(PYTHON) scripts/embed_worker.py _demo
	@echo "==> [5/5] sentinel sweep"
	@$(PYTHON) scripts/sentinel_sweep.py
	@echo "==> stopping Hermes"
	@kill $$(cat .hermes.pid) 2>/dev/null; rm -f .hermes.pid .e2e.json
	@echo "==> smoke complete ✅"

embed:
	@if [ -z "$(T)" ]; then echo "usage: make embed T=<tenant>"; exit 1; fi
	$(PYTHON) scripts/embed_worker.py $(T) $(if $(QUIET),--quiet,)

sentinel:
	$(PYTHON) scripts/sentinel_sweep.py

clean:
	rm -f .hermes.pid .e2e.json

# Coding 01 development workspace

Use the enrolled Coding 01 SSH alias from an authorized Tailscale client. The reviewed platform checkout is `$HOME/Projects/snow-gloves-os`, tracking `origin/feat/cloud-gateway`. The accumulated pilot is reviewed in PR31; it has not been merged to main.

```sh
ssh coding-01-tailnet
cd ~/Projects/snow-gloves-os
git status --short
git pull --ff-only
cd apps/infra-block
npm ci
npm run build
```

The supervised UI serves this checkout's production `dist` through the existing private HTTPS endpoint. After a successful build, refresh the browser. Edit the files under `apps/infra-block/src`; a pull alone does not rebuild the served UI. Run `npm test` and `npm run build` for a UI change. Keep development branches separate from the reviewed baseline and commit changes before switching branches.

The private operations checkout is `$HOME/Projects/snow-gloves-ops`. Private repository authentication must be available in the selected user context before pulling it. The pilot's existing private runtime directory still owns credentials, SQLite, logs and artifacts; it is deliberately outside both new Git checkouts. Never copy the live SQLite file to a shared filesystem or add runtime secrets to Git.

The SSH wrapper `~/.local/bin/snowgloves-fleet` exposes `submit`, `list`, `status`, `logs` and `cancel`. The UI Hermes board uses the same coordinator operations and project authorization. Start with a read-only UI review task:

```sh
~/.local/bin/snowgloves-fleet submit --project snowgloves \
  --title 'UI refinement review' \
  --brief 'Review apps/infra-block/src and propose three scoped improvements to the Hermes task board. Read only; do not modify files or call external services.'
```

The current worker runs one managed read-only Codex attempt at a time. Hermes adds a logical organization role; this does not run seven independent agents. Multi-stage role fan-out, write-enabled attempts and additional nodes require their own implementation and evidence. See [Hermes pilot](HERMES-FLEET-PILOT.md). Team credentials and deployment/external-message permissions remain separate.

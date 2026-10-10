FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tini python3 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp
RUN NODE_OPTIONS=--max-old-space-size=2048 npm pack --silent omniroute@3.8.50 \
    && node -e "if(require('crypto').createHash('sha512').update(require('fs').readFileSync('omniroute-3.8.50.tgz')).digest('base64')!=='qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg==')throw Error('SHA512 mismatch')" \
    && NODE_OPTIONS=--max-old-space-size=2048 npm install -g ./omniroute-3.8.50.tgz --omit=dev --no-audit --no-fund \
    && rm -f ./omniroute-3.8.50.tgz && rm -rf /root/.npm

RUN mkdir -p /data && chown 1000:1000 /data && chmod 0700 /data

RUN mkdir -p /opt/snowgloves/runtime/scripts/lib /opt/snowgloves/runtime/crypto

COPY scripts/lib/runtime_remote_cipher_import.py scripts/lib/runtime_remote_cipher_stage.py scripts/lib/runtime_import_http_contract.py scripts/lib/runtime_import_body_bridge.py scripts/lib/runtime_import_request_registry.py scripts/lib/runtime_remote_cipher_metadata.py scripts/lib/runtime_cipher_export.py scripts/lib/runtime_storage_guard.py scripts/lib/runtime_supervisor.py scripts/lib/runtime_initializer.py scripts/lib/runtime_snapshot.py scripts/lib/runtime_bounded_process.py scripts/lib/runtime_job_journal.py scripts/lib/runtime_restore_intent.py scripts/lib/runtime_operation_identity.py scripts/lib/runtime_management_http.py scripts/lib/runtime_management_coordinator.py scripts/lib/runtime_managed_http.py scripts/lib/runtime_managed_service.py /opt/snowgloves/runtime/scripts/lib/
COPY infra/cloudflare-runtime/backup_crypto.mjs infra/cloudflare-runtime/backup_file_cli.mjs /opt/snowgloves/runtime/crypto/
COPY infra/cloudflare-runtime/entrypoint.py /opt/snowgloves/runtime/entrypoint.py
COPY infra/cloudflare-runtime/start-runtime.sh /opt/snowgloves/runtime/start-runtime.sh

RUN chown -R 0:0 /opt/snowgloves/runtime \
    && chmod 0555 /opt/snowgloves/runtime /opt/snowgloves/runtime/scripts /opt/snowgloves/runtime/scripts/lib /opt/snowgloves/runtime/crypto \
    && chmod 0444 /opt/snowgloves/runtime/scripts/lib/*.py /opt/snowgloves/runtime/crypto/*.mjs /opt/snowgloves/runtime/entrypoint.py \
    && chmod 0555 /opt/snowgloves/runtime/start-runtime.sh

USER node
WORKDIR /data

ENV HOME=/tmp \
    DATA_DIR=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    SG_NODE_EXECUTABLE=/usr/local/bin/node \
    SG_RUNTIME_SCRIPT=/usr/local/lib/node_modules/omniroute/dist/server.js \
    SG_BACKUP_CLI=/opt/snowgloves/runtime/crypto/backup_file_cli.mjs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD /usr/local/bin/node -e 'fetch("http://127.0.0.1:8080/healthz", { signal: AbortSignal.timeout(3000) }).then(res => { if (res.status === 200) { return res.text(); } throw new Error(); }).then(t => { if (t === "ok\n") process.exit(0); else process.exit(1); }).catch(() => process.exit(1));'

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/snowgloves/runtime/start-runtime.sh"]

FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp
RUN NODE_OPTIONS=--max-old-space-size=2048 npm pack --silent omniroute@3.8.50 \
    && node -e "if(require('crypto').createHash('sha512').update(require('fs').readFileSync('omniroute-3.8.50.tgz')).digest('base64')!=='qK6REDWQYGh8lwGwDgFMsBqAMXnxIePudr8cSuSYeB9iIlywNhDJxHKt6Cwa31lPci8jXE5bbvl+az0lvyt0Mg==')throw Error('SHA512 mismatch')" \
    && NODE_OPTIONS=--max-old-space-size=2048 npm install -g ./omniroute-3.8.50.tgz --omit=dev --no-audit --no-fund \
    && rm -f omniroute-3.8.50.tgz && npm cache clean --force
RUN mkdir -p /data && chown 1000:1000 /data
USER node
ENV HOME=/data DATA_DIR=/data PORT=8081 HOSTNAME=0.0.0.0 NEXT_TELEMETRY_DISABLED=1 \
    NODE_OPTIONS="--max-old-space-size=512"
EXPOSE 8081
COPY --chmod=0555 start-runtime.sh /usr/local/bin/start-runtime.sh
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:8081/healthz',{signal:AbortSignal.timeout(3000)}).then(r=>{if(r.status!==200)process.exit(1);return r.text()}).then(t=>process.exit(t==='ok\n'?0:1)).catch(()=>process.exit(1))"
ENTRYPOINT ["tini","--","start-runtime.sh"]

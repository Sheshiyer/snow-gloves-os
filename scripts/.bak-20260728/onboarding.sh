#!/usr/bin/env bash
# Snow Gloves OS — onboarding & source ingestion
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/.snowgloves.env" 2>/dev/null || true

echo "==> Snow Gloves Onboarding"
read -rp "Business name: " BIZ_NAME
read -rp "Tenant slug (lowercase, no spaces): " TENANT
TDIR="$ROOT/tenants/$TENANT"
mkdir -p "$TDIR/sources" "$TDIR/wiki" "$TDIR/docs" "$TDIR/audit"

echo "Where do your source files live? (one path per line, blank to finish)"
SOURCES=()
while true; do
  read -rp "  path: " p
  [ -z "$p" ] && break
  SOURCES+=("$p")
done

# Write sources manifest
{
  echo "tenant: $TENANT"
  echo "business_name: \"$BIZ_NAME\""
  echo "created_at: $(date -u +%FT%TZ)"
  echo "paperclip:"
  echo "  port: ${PAPERCLIP_PORT:-3100}"
  echo "  instance: ${PAPERCLIP_INSTANCE:-default}"
  echo "hermes:"
  echo "  port: ${HERMES_PORT:-4100}"
  echo "sources:"
  for s in "${SOURCES[@]}"; do
    echo "  - path: \"$s\""
    echo "    kind: auto"
    echo "    ingest: true"
  done
} > "$TDIR/sources.yaml"

echo "==> Wrote $TDIR/sources.yaml"
echo "==> Next: run 'python3 scripts/ingest.py $TENANT' to start ingestion."

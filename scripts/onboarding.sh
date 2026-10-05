#!/usr/bin/env bash
# Snow Gloves OS — onboarding & source ingestion (thin wrapper around scripts/onboard.py)
#   no args  -> interactive tenant + sources prompt (the original `make onboard` flow)
#   any args -> passed through, e.g. --steps, --prompt cursor, --apply-harvest f --tenant t
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/.snowgloves.env" 2>/dev/null || true
export PAPERCLIP_PORT="${PAPERCLIP_PORT:-3100}" PAPERCLIP_INSTANCE="${PAPERCLIP_INSTANCE:-default}" HERMES_PORT="${HERMES_PORT:-4100}"
if [ -n "${SNOWGLOVES_DATA:-}" ]; then export SNOWGLOVES_DATA; fi   # private data checkout (tenants/)

if [ "$#" -eq 0 ]; then
  exec "${PYTHON:-python3}" "$ROOT/scripts/onboard.py" --init-tenant
fi
exec "${PYTHON:-python3}" "$ROOT/scripts/onboard.py" "$@"

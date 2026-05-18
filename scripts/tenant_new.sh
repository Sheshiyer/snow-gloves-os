#!/usr/bin/env bash
set -euo pipefail
T="${1:?usage: tenant_new.sh <slug> [business_name]}"
NAME="${2:-$T}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TDIR="$ROOT/tenants/$T"
[ -d "$TDIR" ] && { echo "tenant exists: $TDIR"; exit 1; }
mkdir -p "$TDIR"/{sources,connectors,approvals,audit,agents,wiki,docs,_embed_cache}
cat > "$TDIR/MANIFEST.yaml" <<EOF
tenant: $T
business_name: "$NAME"
created_at: $(date -u +%FT%TZ)
paperclip:
  company_id: ""    # fill in after paperclip company exists
  lane_prefix: ""
isolation: strict
status: active
EOF
cat > "$TDIR/sources.yaml" <<EOF
tenant: $T
sources: []
EOF
REG="$ROOT/tenants/_registry.yaml"
if [ ! -f "$REG" ]; then echo "tenants:" > "$REG"; fi
grep -q "  - $T" "$REG" || echo "  - $T  # $NAME" >> "$REG"
echo "✅ tenant created: $TDIR"
echo "   next: edit MANIFEST.yaml (paperclip.company_id) and add sources.yaml entries"

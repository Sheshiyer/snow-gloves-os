#!/usr/bin/env bash
# Pre-flight diagnostic for Snow Gloves OS
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GREEN='\033[0;32m'; RED='\033[0;31m'; YEL='\033[0;33m'; NC='\033[0m'
pass(){ printf "  ${GREEN}✓${NC} %s\n" "$1"; }
fail(){ printf "  ${RED}✗${NC} %s\n" "$1"; FAILED=$((FAILED+1)); }
warn(){ printf "  ${YEL}!${NC} %s\n" "$1"; }
FAILED=0

echo "== Snow Gloves doctor =="

# 1 tooling
command -v python3 >/dev/null && pass "python3"   || fail "python3 missing"
command -v node    >/dev/null && pass "node"      || fail "node missing"
command -v paperclipai >/dev/null && pass "paperclipai" || warn "paperclipai not installed (run make install)"
python3 -c "import yaml" 2>/dev/null && pass "python: pyyaml" || fail "pip install pyyaml"

# 2 ports
for P in 4100 3100; do
  if lsof -i tcp:$P -sTCP:LISTEN >/dev/null 2>&1; then
    [ "$P" = "3100" ] && pass "port $P: paperclip listening" || warn "port $P busy (kill before make smoke)"
  else
    [ "$P" = "3100" ] && warn "port $P: paperclip NOT running (bridge will queue)" || pass "port $P free"
  fi
done

# 3 config + files
[ -f "$ROOT/config/snowgloves.yaml" ]   && pass "config/snowgloves.yaml" || fail "missing snowgloves.yaml"
[ -f "$ROOT/workflows/skill-hooks.yaml" ] && pass "workflows/skill-hooks.yaml" || fail "missing skill-hooks.yaml"
[ -f "$ROOT/connectors/g-stack/capabilities.yaml" ] && pass "g-stack capabilities" || fail "missing capabilities.yaml"
python3 -c "import yaml; yaml.safe_load(open('$ROOT/workflows/skill-hooks.yaml'))" 2>/dev/null && pass "skill-hooks parses" || fail "skill-hooks malformed"

# 4 audit + tenants
[ -w "$ROOT" ] && pass "repo writable" || fail "repo not writable"
mkdir -p "$ROOT/_audit"; touch "$ROOT/_audit/.probe" && rm "$ROOT/_audit/.probe" && pass "_audit writable" || fail "_audit not writable"
if [ -f "$ROOT/tenants/_registry.yaml" ]; then
  N=$(grep -c "^  - " "$ROOT/tenants/_registry.yaml" 2>/dev/null || echo 0)
  pass "tenants registered: $N"
else
  warn "no tenants yet (run: bash scripts/tenant_new.sh <slug>)"
fi

# 5 secrets / keys
[ -n "${NVIDIA_API_KEY:-}" ] && pass "NVIDIA_API_KEY set" || warn "NVIDIA_API_KEY not set (embed uses stub)"

echo
if [ "$FAILED" -gt 0 ]; then
  printf "${RED}FAIL${NC} ($FAILED issues)\n"; exit 1
else
  printf "${GREEN}OK${NC} — system healthy\n"
fi

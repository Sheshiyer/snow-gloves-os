#!/usr/bin/env bash
# Snow Gloves OS — bootstrap installer
# Installs Paperclip, sets Hermes port, installs deps, runs onboarding.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$ROOT/config/snowgloves.yaml"

echo "==> Snow Gloves OS installer"
echo "    Repo: $ROOT"

# --- 1. Tooling checks ----------------------------------------------------
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1"; MISSING=1; }; }
MISSING=0
need node
need npm
need python3
need git
need curl
[ "${MISSING:-0}" = "1" ] && { echo "Install missing tools and retry."; exit 1; }

# --- 2. Read ports from config -------------------------------------------
get_yaml() { python3 -c "import yaml,sys;print(yaml.safe_load(open('$CONF'))$1)"; }
PAPERCLIP_PORT=$(get_yaml "['paperclip']['port']")
HERMES_PORT=$(get_yaml "['hermes']['port']")
PAPERCLIP_INSTANCE=$(get_yaml "['paperclip']['instance']")

echo "    Paperclip port: $PAPERCLIP_PORT (instance: $PAPERCLIP_INSTANCE)"
echo "    Hermes port:    $HERMES_PORT"

# --- 3. Install Paperclip (paperclipai) ----------------------------------
if ! command -v paperclipai >/dev/null 2>&1; then
  echo "==> Installing paperclipai (global)"
  npm install -g paperclipai
else
  echo "==> paperclipai already installed: $(paperclipai --version 2>/dev/null || echo unknown)"
fi

# --- 4. Python deps for ingestion + embeddings ---------------------------
echo "==> Installing Python deps"
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet pyyaml httpx tiktoken rich watchdog

# --- 5. Export runtime env -----------------------------------------------
ENV_FILE="$ROOT/.snowgloves.env"
cat > "$ENV_FILE" <<ENV
PAPERCLIP_PORT=$PAPERCLIP_PORT
PAPERCLIP_INSTANCE=$PAPERCLIP_INSTANCE
HERMES_PORT=$HERMES_PORT
SNOWGLOVES_ROOT=$ROOT
ENV
echo "    Wrote $ENV_FILE"

# --- 6. Hand off to onboarding -------------------------------------------
echo "==> Launching onboarding"
bash "$ROOT/scripts/onboarding.sh"

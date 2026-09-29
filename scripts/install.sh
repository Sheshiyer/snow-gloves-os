#!/usr/bin/env bash
# Snow Gloves OS — bootstrap installer
# Checks tools, installs paperclipai + Python deps, writes .snowgloves.env,
# then prints the four onboarding steps. Does not start Hermes, Paperclip host,
# or enable catalog modules. Legacy tenant prompt: make onboard.

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

# Config parse needs PyYAML before the rest of the Python deps.
if ! python3 -c "import yaml" 2>/dev/null; then
  echo "==> Installing pyyaml (required to read config/snowgloves.yaml)"
  python3 -m pip install --quiet pyyaml || python3 -m pip install --quiet --user pyyaml
fi

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

# --- 6. Print next steps (the glove is not live yet) ---------------------
echo "==> Install finished: paperclipai CLI (if missing), Python deps, $ENV_FILE"
echo "    Catalog modules are not enabled. Hermes is not a daemon"
echo "    (run \`make hermes\` in the foreground when you need the bus)."
echo "    Paperclip here is the npm CLI; the host instance is still a placeholder."
echo "    Embeddings use the stub backend unless NVIDIA_API_KEY is set."
echo
echo "    First hour:"
echo "      1. make doctor"
echo "      2. make smoke"
echo "      3. make onboard-prompt R=<runtime>   # claude, cursor, codex, hermes, grok, …"
echo "      4. paste that prompt in plan mode, then apply / enable / render"
echo
echo "    Optional legacy tenant + sources prompt: make onboard"
echo
"${PYTHON:-python3}" "$ROOT/scripts/onboard.py" --steps

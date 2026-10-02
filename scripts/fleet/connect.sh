#!/usr/bin/env bash
# Snow Gloves fleet: open a Screen Sharing or SSH session to one wing over Tailscale.
#
#   connect.sh <wing> [screen|ssh] [--print] [--lan] [--fleet fleet.yaml]
#
# Resolves the wing's overlay name and operator user from fleet.yaml (or $SNOWGLOVES_FLEET)
# and runs `open vnc://<user>@<overlay>` (default) or `ssh <user>@<overlay>`.
# `--lan` (or SNOWGLOVES_LAN=1) uses the wing's `lan_host` instead of the Tailscale overlay name.
# --print shows the command instead of running it.
set -euo pipefail

usage() {
  echo "usage: connect.sh <marketing|design|coding> [screen|ssh] [--print] [--lan] [--fleet fleet.yaml]" >&2
}

WING=""
MODE="screen"
PRINT=0
FLEET="${SNOWGLOVES_FLEET:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --print)   PRINT=1; shift ;;
    --lan)     export SNOWGLOVES_LAN=1; shift ;;
    --fleet)   FLEET="${2:-}"; shift 2 ;;
    --fleet=*) FLEET="${1#--fleet=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    screen|ssh) MODE="$1"; shift ;;
    -*) echo "connect.sh: unknown flag: $1" >&2; usage; exit 2 ;;
    *)
      if [ -z "$WING" ]; then
        WING="$1"
      else
        echo "connect.sh: unexpected argument: $1" >&2; usage; exit 2
      fi
      shift ;;
  esac
done

if [ -z "$WING" ]; then
  usage
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -z "$FLEET" ]; then
  FLEET="$SCRIPT_DIR/../../fleet.yaml"
fi
if [ ! -f "$FLEET" ]; then
  echo "connect.sh: fleet inventory not found: $FLEET" >&2
  exit 2
fi

read_fleet() {
  python3 - "$FLEET" "$WING" <<'PY'
import sys
try:
    import yaml
except ImportError:
    sys.stderr.write("connect.sh: python3 needs pyyaml (python3 -m pip install --user pyyaml)\n")
    sys.exit(2)
path, wing = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    data = yaml.safe_load(fh) or {}
wings = data.get("wings") or {}
if wing not in wings:
    known = ", ".join(sorted(wings)) or "(none)"
    sys.stderr.write(f"connect.sh: unknown wing '{wing}'. Known wings: {known}\n")
    sys.exit(3)
w = wings[wing] or {}
import os
if os.environ.get("SNOWGLOVES_LAN") == "1" and w.get("lan_host"):
    print(w["lan_host"])
else:
    print(w.get("overlay") or w.get("hostname") or "")
print(w.get("operator_user") or "")
PY
}

if ! FACTS=$(read_fleet); then
  exit 3
fi
{ read -r OVERLAY; read -r OPERATOR; } <<<"$FACTS"
if [ -z "$OVERLAY" ] || [ -z "$OPERATOR" ]; then
  echo "connect.sh: wing '$WING' is missing overlay or operator_user in $FLEET" >&2
  exit 3
fi

case "$MODE" in
  screen)
    CMD=(open "vnc://$OPERATOR@$OVERLAY")
    ;;
  ssh)
    CMD=(ssh "$OPERATOR@$OVERLAY")
    ;;
esac

if [ "$PRINT" -eq 1 ]; then
  echo "${CMD[*]}"
  exit 0
fi

if [ "$MODE" = "ssh" ]; then
  exec "${CMD[@]}"
fi
echo "+ ${CMD[*]}"
"${CMD[@]}"

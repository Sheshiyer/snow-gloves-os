#!/usr/bin/env bash
# Snow Gloves fleet: name one Mac mini, create its users, turn on Remote Management
# (Apple Remote Desktop / Screen Sharing), Remote Login (SSH) and the always-on power policy.
#
# DRY-RUN BY DEFAULT. Nothing is changed unless you pass --apply.
# Human guide: docs/fleet/02-NETWORK-REMOTE-ACCESS.md and docs/fleet/01-APPLE-ACCOUNT.md.
set -euo pipefail

usage() {
  cat <<'USAGE'
usage: remote_access.sh --wing <marketing|design|coding> [--apply] [--fleet fleet.yaml]

Reads the wing's hostname, operator user and admin user from fleet.yaml
(or $SNOWGLOVES_FLEET) and prints every command it would run.

  --apply   run the commands (most need sudo; you will be asked for passwords
            of new users on the terminal, they are never echoed)
  --fleet   path to the inventory (default: <repo>/fleet.yaml)
USAGE
}

WING=""
APPLY=0
FLEET="${SNOWGLOVES_FLEET:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --wing)    WING="${2:-}"; shift 2 ;;
    --wing=*)  WING="${1#--wing=}"; shift ;;
    --apply)   APPLY=1; shift ;;
    --fleet)   FLEET="${2:-}"; shift 2 ;;
    --fleet=*) FLEET="${1#--fleet=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "remote_access.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$WING" ]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -z "$FLEET" ]; then
  FLEET="$SCRIPT_DIR/../../fleet.yaml"
fi
if [ ! -f "$FLEET" ]; then
  echo "remote_access.sh: fleet inventory not found: $FLEET" >&2
  exit 2
fi

# --- read the wing from fleet.yaml -------------------------------------------------
read_fleet() {
  python3 - "$FLEET" "$WING" <<'PY'
import sys
try:
    import yaml
except ImportError:
    sys.stderr.write("remote_access.sh: python3 needs pyyaml (python3 -m pip install --user pyyaml)\n")
    sys.exit(2)
path, wing = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    data = yaml.safe_load(fh) or {}
wings = data.get("wings") or {}
if wing not in wings:
    known = ", ".join(sorted(wings)) or "(none)"
    sys.stderr.write(f"remote_access.sh: unknown wing '{wing}'. Known wings: {known}\n")
    sys.exit(3)
w = wings[wing] or {}
print(w.get("hostname") or "")
print(w.get("operator_user") or "")
print(data.get("admin_user") or "sg-admin")
print("1" if w.get("always_on") else "0")
PY
}

if ! FACTS=$(read_fleet); then
  exit 3
fi
{ read -r HOST_NAME; read -r OPERATOR; read -r ADMIN; read -r ALWAYS_ON; } <<<"$FACTS"

if [ -z "$HOST_NAME" ] || [ -z "$OPERATOR" ]; then
  echo "remote_access.sh: wing '$WING' is missing hostname or operator_user in $FLEET" >&2
  exit 3
fi

# --- helpers -----------------------------------------------------------------------
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

quoted() {
  # shell-quote arguments so printed lines can be pasted as is:
  # plain tokens stay bare, anything else is single-quoted (stable across bash versions,
  # unlike printf %q which escapes commas on some builds)
  local out="" a
  for a in "$@"; do
    case "$a" in
      ''|*[!A-Za-z0-9_./:@=,+-]*) out+="'${a//\'/\'\\\'\'}' " ;;
      *) out+="$a " ;;
    esac
  done
  printf '%s' "${out% }"
}

run() {
  if [ "$APPLY" -eq 1 ]; then
    echo "+ $(quoted "$@")"
    "$@"
  else
    echo "[dry-run] $(quoted "$@")"
  fi
}

run_root() {
  # shellcheck disable=SC2086
  run $SUDO "$@"
}

user_exists() {
  id -u "$1" >/dev/null 2>&1
}

ensure_user() {
  local name="$1" full="$2" kind="$3"
  if user_exists "$name"; then
    echo "user $name already exists; leaving it as is"
    return 0
  fi
  if [ "$kind" = "admin" ]; then
    run_root sysadminctl -addUser "$name" -fullName "$full" -admin -password -
  else
    run_root sysadminctl -addUser "$name" -fullName "$full" -password -
  fi
}

operator_home() {
  local home=""
  if user_exists "$OPERATOR"; then
    home=$(dscl . -read "/Users/$OPERATOR" NFSHomeDirectory 2>/dev/null | awk '{print $2}' || true)
  fi
  echo "${home:-/Users/$OPERATOR}"
}

KICKSTART=/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart
SSH_GROUP=com.apple.access_ssh

# --- banner ------------------------------------------------------------------------
echo "Snow Gloves fleet: remote access for wing '$WING'"
echo "  inventory      : $FLEET"
echo "  hostname       : $HOST_NAME"
echo "  admin user     : $ADMIN"
echo "  operator user  : $OPERATOR"
echo "  always on      : $([ "$ALWAYS_ON" = 1 ] && echo yes || echo no)"
if [ "$APPLY" -eq 1 ]; then
  echo "  mode           : APPLY (commands below run with $SUDO; expect password prompts)"
else
  echo "  mode           : dry-run (nothing is changed; add --apply to run)"
fi
echo

echo "## 1. Computer name (fleet.yaml hostname)"
run_root scutil --set ComputerName "$HOST_NAME"
run_root scutil --set HostName "$HOST_NAME"
run_root scutil --set LocalHostName "$HOST_NAME"
echo

echo "## 2. Users: $ADMIN (admin) and $OPERATOR (standard, daily operator)"
echo "   sysadminctl asks for each new password on the terminal and never echoes it."
ensure_user "$ADMIN" "Snow Gloves Admin" admin
ensure_user "$OPERATOR" "Snow Gloves ${WING} operator" standard
echo

echo "## 3. Remote Management (Apple Remote Desktop + Screen Sharing, TCP 5900 / 3283)"
echo "   Note: on macOS 10.14 and later Apple documents that kickstart cannot grant Remote"
echo "   Management the very first time. If this step reports no change, turn it on once in"
echo "   System Settings > General > Sharing > Remote Management, then rerun. See man kickstart."
run_root "$KICKSTART" -activate -configure -access -on -users "$ADMIN,$OPERATOR" -privs -all -restart -agent -menu
echo

echo "## 4. Remote Login (SSH, TCP 22) limited to $ADMIN and $OPERATOR"
run_root systemsetup -setremotelogin on
if [ "$APPLY" -eq 1 ]; then
  if ! dseditgroup -o read "$SSH_GROUP" >/dev/null 2>&1; then
    run_root dseditgroup -o create -q "$SSH_GROUP"
  fi
else
  echo "[dry-run] (only if the group is missing) $SUDO dseditgroup -o create -q $SSH_GROUP"
fi
run_root dseditgroup -o edit -a "$ADMIN" -t user "$SSH_GROUP"
run_root dseditgroup -o edit -a "$OPERATOR" -t user "$SSH_GROUP"
echo

echo "## 5. Power: never sleep, display off after 10 min, restart after power failure, wake on LAN"
run_root pmset -a sleep 0 displaysleep 10 autorestart 1 womp 1
echo

echo "## 6. FileVault (reported, never changed by this script)"
fdesetup status 2>/dev/null || echo "   fdesetup status: unavailable"
echo "   Reminder: FileVault on, recovery key in the company password manager, never in git."
echo "   See docs/fleet/01-APPLE-ACCOUNT.md."
echo

echo "## 7. Wing identity for scripts: SNOWGLOVES_NODE=$WING"
run launchctl setenv SNOWGLOVES_NODE "$WING"
RC_FILE="$(operator_home)/.zshrc"
RC_LINE="export SNOWGLOVES_NODE=$WING"
if [ "$APPLY" -eq 1 ]; then
  if [ -d "$(dirname "$RC_FILE")" ]; then
    if [ -f "$RC_FILE" ] && grep -qxF "$RC_LINE" "$RC_FILE"; then
      echo "   $RC_FILE already exports SNOWGLOVES_NODE"
    else
      echo "+ append '$RC_LINE' to $RC_FILE"
      printf '\n# Snow Gloves fleet wing\n%s\n' "$RC_LINE" | $SUDO tee -a "$RC_FILE" >/dev/null
      $SUDO chown "$OPERATOR" "$RC_FILE" 2>/dev/null || true
    fi
  else
    echo "   home for $OPERATOR not found yet; log in once as $OPERATOR, then rerun --apply"
  fi
else
  echo "[dry-run] append '$RC_LINE' to $RC_FILE (if absent)"
fi
echo

echo "Next: Tailscale (docs/fleet/02-NETWORK-REMOTE-ACCESS.md), then from a team Mac:"
echo "  bash scripts/fleet/connect.sh $WING          # Screen Sharing"
echo "  bash scripts/fleet/connect.sh $WING ssh      # SSH"
if [ "$APPLY" -eq 0 ]; then
  echo "Dry-run complete. Rerun with --apply on the mini itself to make these changes."
fi

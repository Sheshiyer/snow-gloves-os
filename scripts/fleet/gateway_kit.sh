#!/usr/bin/env bash
# Snow Gloves fleet gateway kit.
#   export  (authoring seat)  -> dist/fleet/gateway-kit-<UTC stamp>.tar.gz + MANIFEST.sha256
#   verify  (anywhere)        -> recompute every checksum against the MANIFEST inside the tarball
#   import  (Coding Mac)      -> verify, extract to ~/.snowgloves-kit/<name>/, print or run host steps
#
# The kit never carries secrets: plist values whose key matches KEY|TOKEN|SECRET|PASSWORD are
# replaced by REDACTED, a leak guard aborts the export if anything secret-shaped is staged, and
# import never performs OAuth or writes a secret. Import is dry-run unless --apply is given.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
TE_ROOT="${TEMPERANCE_ROOT:-$HOME/.temperance_engine}"
PLIST_LABEL="com.temperance.engine.omniroute"
PLIST_SRC="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LANE_TEMPLATE="$TE_ROOT/state/lane-templates-from-live.json"
PHASE_CORE="$TE_ROOT/router/phase-combo-core.v4.json"
SYNC_FLEET="${SYNC_PROVIDER_FLEET:-$HOME/.agents/skills/temperance-parallel-dispatch/scripts/sync-provider-fleet.py}"
KIT_HOME="$HOME/.snowgloves-kit"
LEAK_RE='sk-[A-Za-z0-9]{10,}|Bearer [A-Za-z0-9._-]{20,}'
GATEWAY_PORT=20128

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

sha_cmd() {
  if command -v shasum >/dev/null 2>&1; then echo "shasum -a 256"
  elif command -v sha256sum >/dev/null 2>&1; then echo "sha256sum"
  else die "no sha256 tool (shasum or sha256sum) on PATH" 5; fi
}

usage() {
  cat <<'EOF'
usage: gateway_kit.sh <command> [options]

  export [--out DIR] [--tailscale-ip IP] [--repo DIR]
      Stage fleet.yaml, nodes/, redacted host state and client templates; write
      DIR/gateway-kit-<stamp>.tar.gz and DIR/MANIFEST.sha256 (default DIR: <repo>/dist/fleet).
      --tailscale-ip writes that IP into the plist instead of the ${TAILSCALE_IP} placeholder.
  verify <tar>
      Recompute sha256 of every file against the MANIFEST.sha256 inside the tarball.
  import <tar> [--dry-run|--apply]
      Verify, extract to ~/.snowgloves-kit/<name>/, then print (dry-run, default) or run (--apply)
      the host steps. Never performs OAuth. Never writes a secret.
EOF
}

signin_checklist() {
  cat <<'EOF'
Interactive sign-in checklist (run ON the Coding Mac over Screen Sharing, as the wing operator user;
OAuth tokens never travel in the kit, so every subscription seat is signed in here, once):
  1. Claude Code : run `claude`, type `/login`, finish the browser flow, confirm with `/status`.
  2. Codex       : run `codex login`, finish the browser flow, confirm with `codex login status`.
  3. Grok CLI    : run `grok`, complete the sign-in prompt, send one short test prompt.
  4. Cursor      : open Cursor.app and sign in; then in the OmniRoute dashboard re-test the `cursor` connection.
  5. OmniRoute   : open http://<tailscale-ip>:20128/dashboard, rotate the dashboard password
                   (`omniroute reset-password`), re-authorize OAuth providers (codex, claude, cursor,
                   antigravity) under Providers, and mint one scoped API key per machine and person.
  6. Each client : store its scoped key in Keychain (`security add-generic-password -a snowgloves
                   -s snowgloves-gateway-<wing> -w`), then run
                   `python3 scripts/fleet/gateway_client.py set-url --host coding-mac --key-ref keychain:snowgloves-gateway-<wing> --apply`
                   followed by `... status`.
EOF
}

# ------------------------------------------------------------------------------------------ export

gateway_url_from_fleet() {
  local fleet="$1" url
  url="$(grep -E '^[[:space:]]*url:' "$fleet" | head -1 | sed -E 's/.*"(https?:[^"]+)".*/\1/')"
  [[ "$url" == http* ]] && printf '%s' "$url" || printf 'http://coding-mac:%s' "$GATEWAY_PORT"
}

write_redacted_plist() {
  # args: src dst tailscale_value home_prefix
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import re, sys
src, dst, ts_value, home = sys.argv[1:5]
text = open(src, encoding="utf-8").read()
seen_host = False

def sub(m):
    global seen_host
    key, ws, value = m.group(1), m.group(2), m.group(3)
    if re.search(r"KEY|TOKEN|SECRET|PASSWORD", key, re.I):
        value = "REDACTED"
    elif key == "OMNIROUTE_SERVER_HOST":
        value = ts_value
        seen_host = True
    return f"<key>{key}</key>{ws}<string>{value}</string>"

text = re.sub(r"<key>([^<]+)</key>(\s*)<string>([^<]*)</string>", sub, text)
if not seen_host:
    text = re.sub(
        r"(<key>EnvironmentVariables</key>\s*<dict>)",
        lambda m: m.group(1) + f"\n\t\t<key>OMNIROUTE_SERVER_HOST</key>\n\t\t<string>{ts_value}</string>",
        text, count=1,
    )
if home:
    text = text.replace(home, "${HOME}")
open(dst, "w", encoding="utf-8").write(text)
PY
}

write_providers_txt() {
  # args: lane_template dst
  python3 - "$1" "$2" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
lines = ["# Provider ids seen in lane templates (names only). Classes: docs/fleet/PROVIDERS.md."]
try:
    data = json.load(open(src, encoding="utf-8"))
    provs = set()
    for combo in data.values():
        for seat in (combo.get("seats") or []) if isinstance(combo, dict) else []:
            if isinstance(seat, str) and "/" in seat:
                provs.add(seat.split("/", 1)[0])
    lines += sorted(provs) if provs else ["see dashboard"]
except Exception:
    lines += ["see dashboard"]
open(dst, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
}

write_client_templates() {
  local dir="$1" root="$2" v1="$2/v1"
  mkdir -p "$dir"
  cat >"$dir/claude.settings.json" <<EOF
{
  "env": {
    "ANTHROPIC_BASE_URL": "$root",
    "ANTHROPIC_AUTH_TOKEN": "\${OMNIROUTE_API_KEY}"
  }
}
EOF
  cat >"$dir/codex.config.toml" <<EOF
# merge into ~/.codex/config.toml (or let gateway_client.py set-url do it)
model_provider = "omniroute"

[model_providers.omniroute]
name = "OmniRoute"
base_url = "$v1"
wire_api = "responses"
env_key = "OMNIROUTE_API_KEY"
EOF
  {
    echo "# merge into ~/.grok/config.toml (or let gateway_client.py set-url do it)"
    for combo in orchestrator build fast plan; do
      cat <<EOF

[model.te-$combo]
model = "noesis-$combo"
base_url = "$v1"
name = "Fleet noesis-$combo"
env_key = ["OMNIROUTE_API_KEY"]
api_backend = "chat_completions"
context_window = 200000
EOF
    done
  } >"$dir/grok.config.toml"
  cat >"$dir/opencode.json" <<EOF
{
  "provider": {
    "omniroute": {
      "name": "OmniRoute",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "$v1",
        "apiKey": "{env:OMNIROUTE_API_KEY}"
      }
    }
  }
}
EOF
}

write_import_readme() {
  local dst="$1" name="$2"
  {
    cat <<EOF
# $name: import on the Coding Mac

Verify, then import (dry-run first, then apply):

    bash scripts/fleet/gateway_kit.sh verify $name.tar.gz
    bash scripts/fleet/gateway_kit.sh import $name.tar.gz
    bash scripts/fleet/gateway_kit.sh import $name.tar.gz --apply

Import runs these host steps (apply) or prints them (dry-run):
  1. ~/.temperance_engine/bin/te-install.sh if present, else prints the install pointer.
  2. temperance-install-launchers --apply if present.
  3. Renders host/$PLIST_LABEL.plist with \${TAILSCALE_IP} from \`tailscale ip -4\` and \${HOME},
     backs up any existing LaunchAgent plist, writes the new one. Refuses while any REDACTED value remains.
  4. launchctl bootout (ignored if absent) then bootstrap gui/\$(id -u) and kickstart -k.
  5. Copies lane-templates-from-live.json and phase-combo-core.v4.json only where the host has none.
  6. sync-provider-fleet.py dry-run, then prompts before --apply. Never hand-edit combos.
  7. curl http://<tailscale-ip>:20128/healthz, then the sign-in checklist below.

EOF
    signin_checklist
  } >"$dst"
}

cmd_export() {
  local out="" ts_ip="" repo="$DEFAULT_REPO"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --out) out="${2:?--out needs a dir}"; shift 2 ;;
      --tailscale-ip) ts_ip="${2:?--tailscale-ip needs a value}"; shift 2 ;;
      --repo) repo="${2:?--repo needs a dir}"; shift 2 ;;
      -h|--help) usage; return 0 ;;
      *) die "export: unknown option $1" 2 ;;
    esac
  done
  [[ -n "$out" ]] || out="$repo/dist/fleet"
  [[ -f "$repo/fleet.yaml" ]] || die "missing $repo/fleet.yaml" 2
  local sha; sha="$(sha_cmd)"
  local stamp name work stage
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  name="gateway-kit-$stamp"
  work="$(mktemp -d)"
  stage="$work/$name"
  trap "rm -rf '$work'" EXIT
  mkdir -p "$stage/host" "$stage/client-templates"

  cp "$repo/fleet.yaml" "$stage/fleet.yaml"
  if [[ -d "$repo/nodes" ]]; then
    mkdir -p "$stage/nodes"
    find "$repo/nodes" -mindepth 1 -maxdepth 1 ! -name '.*' -exec cp -R {} "$stage/nodes/" \;
  fi

  local ts_value='${TAILSCALE_IP}'
  [[ -n "$ts_ip" ]] && ts_value="$ts_ip"
  if [[ -f "$PLIST_SRC" ]]; then
    write_redacted_plist "$PLIST_SRC" "$stage/host/$PLIST_LABEL.plist" "$ts_value" "$HOME"
  else
    log "note: no $PLIST_SRC on this seat; kit carries no LaunchAgent plist"
  fi
  [[ -f "$LANE_TEMPLATE" ]] && cp "$LANE_TEMPLATE" "$stage/host/lane-templates-from-live.json"
  [[ -f "$PHASE_CORE" ]] && cp "$PHASE_CORE" "$stage/host/phase-combo-core.v4.json"
  write_providers_txt "$LANE_TEMPLATE" "$stage/host/providers.txt"

  local gateway_url; gateway_url="$(gateway_url_from_fleet "$repo/fleet.yaml")"
  write_client_templates "$stage/client-templates" "$gateway_url"
  write_import_readme "$stage/README-IMPORT.md" "$name"
  {
    echo "kit: $name"
    echo "created_utc: $stamp"
    echo "authoring_host: $(hostname)"
    echo "gateway_url: $gateway_url"
    if [[ -n "$ts_ip" ]]; then echo "tailscale_ip: $ts_ip"; else echo 'tailscale_ip: ${TAILSCALE_IP} (filled on import from tailscale ip -4)'; fi
  } >"$stage/host/KIT-INFO.txt"
  find "$stage" \( -name '.DS_Store' -o -name '._*' \) -delete

  # secret leak guard: abort before any archive is written
  local leaks
  leaks="$(grep -rIl -E "$LEAK_RE" "$stage" || true)"
  if [[ -n "$leaks" ]]; then
    printf 'ERROR: secret leak guard matched staged files (names only):\n' >&2
    printf '%s\n' "$leaks" | sed "s#^$stage/#  #" >&2
    die "export aborted; nothing written" 3
  fi

  ( cd "$stage" && find . -type f ! -name MANIFEST.sha256 | LC_ALL=C sort | xargs $sha ) >"$stage/MANIFEST.sha256"
  mkdir -p "$out"
  ( cd "$work" && COPYFILE_DISABLE=1 tar -czf "$out/$name.tar.gz" "$name" )
  cp "$stage/MANIFEST.sha256" "$out/MANIFEST.sha256"
  log "kit: $out/$name.tar.gz"
  log "manifest: $out/MANIFEST.sha256 ($(wc -l <"$stage/MANIFEST.sha256" | tr -d ' ') files)"
  log "tarball sha256: $($sha "$out/$name.tar.gz" | awk '{print $1}')"
  log "next: move the tarball to the Coding Mac (Taildrop or scp over the tailnet), then verify + import."
}

# ------------------------------------------------------------------------------------------ verify

extract_kit() {
  # args: tar dest ; prints the top-level kit dir
  local tar="$1" dest="$2" top
  [[ -f "$tar" ]] || die "no such tarball: $tar" 2
  mkdir -p "$dest"
  tar -xzf "$tar" -C "$dest"
  top="$(find "$dest" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [[ -n "$top" ]] || die "tarball has no top-level directory" 4
  printf '%s' "$top"
}

verify_dir() {
  local top="$1" sha; sha="$(sha_cmd)"
  [[ -f "$top/MANIFEST.sha256" ]] || die "MANIFEST.sha256 missing inside kit" 4
  local listed actual
  listed="$(awk '{print $2}' "$top/MANIFEST.sha256" | LC_ALL=C sort)"
  actual="$(cd "$top" && find . -type f ! -name MANIFEST.sha256 | LC_ALL=C sort)"
  if [[ "$listed" != "$actual" ]]; then
    log "verify: FAIL (file set differs from MANIFEST)"
    diff <(printf '%s\n' "$listed") <(printf '%s\n' "$actual") || true
    return 4
  fi
  if ( cd "$top" && $sha -c MANIFEST.sha256 >/dev/null 2>&1 ); then
    log "verify: OK ($(printf '%s\n' "$listed" | wc -l | tr -d ' ') files match MANIFEST.sha256)"
    return 0
  fi
  log "verify: FAIL (checksum mismatch)"
  ( cd "$top" && $sha -c MANIFEST.sha256 2>&1 | grep -v ': OK$' ) || true
  return 4
}

cmd_verify() {
  local tar="${1:-}"; [[ -n "$tar" ]] || { usage; die "verify needs <tar>" 2; }
  local work; work="$(mktemp -d)"; trap "rm -rf '$work'" EXIT
  local top; top="$(extract_kit "$tar" "$work")"
  verify_dir "$top"
}

# ------------------------------------------------------------------------------------------ import

run_or_print() {
  # args: apply(0/1) description command...
  local apply="$1" desc="$2"; shift 2
  if [[ "$apply" == 1 ]]; then
    log "run : $desc"
    log "      $*"
    "$@"
  else
    log "plan: $desc"
    log "      $*"
  fi
}

cmd_import() {
  local tar="${1:-}"; [[ -n "$tar" ]] || { usage; die "import needs <tar>" 2; }
  shift
  local apply=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --apply) apply=1; shift ;;
      --dry-run) apply=0; shift ;;
      *) die "import: unknown option $1" 2 ;;
    esac
  done
  local work; work="$(mktemp -d)"; trap "rm -rf '$work'" EXIT
  local top; top="$(extract_kit "$tar" "$work")"
  verify_dir "$top" || die "import refused: kit failed verification" 4
  local name; name="$(basename "$top")"
  local kit="$KIT_HOME/$name"
  rm -rf "$kit"; mkdir -p "$KIT_HOME"; cp -R "$top" "$kit"
  log "extracted: $kit"
  log "mode: $([[ $apply == 1 ]] && echo APPLY || echo 'dry-run (pass --apply to run the steps)')"

  # 1. host runtime
  if [[ -x "$TE_ROOT/bin/te-install.sh" ]]; then
    run_or_print "$apply" "Temperance host install/refresh" bash "$TE_ROOT/bin/te-install.sh"
  else
    log "plan: Temperance host runtime missing at $TE_ROOT. Install it first (clone the temperance_engine"
    log "      repo to ~/.temperance_engine and run its install.sh), then re-run this import."
  fi
  # 2. launchers
  local launchers=""
  if command -v temperance-install-launchers >/dev/null 2>&1; then launchers="$(command -v temperance-install-launchers)"
  elif [[ -x "$TE_ROOT/bin/temperance-install-launchers" ]]; then launchers="$TE_ROOT/bin/temperance-install-launchers"; fi
  if [[ -n "$launchers" ]]; then
    run_or_print "$apply" "install local launchers" "$launchers" --apply || log "      (launchers reported a problem; continue manually)"
  else
    log "plan: temperance-install-launchers not found; skipped"
  fi
  # 3. plist
  local plist_src="$kit/host/$PLIST_LABEL.plist" plist_dst="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
  local rendered="$kit/rendered.$PLIST_LABEL.plist"
  if [[ -f "$plist_src" ]]; then
    local ts_ip=""
    if command -v tailscale >/dev/null 2>&1; then ts_ip="$(tailscale ip -4 2>/dev/null | head -1 || true)"; fi
    if [[ -z "$ts_ip" ]]; then
      log "plan: Tailscale IP unknown (tailscale missing or not signed in); plist keeps \${TAILSCALE_IP} until it is."
      [[ $apply == 1 ]] && die "import --apply needs Tailscale installed and signed in on this Mac (tailscale ip -4)" 6
    fi
    sed -e "s#\${TAILSCALE_IP}#${ts_ip:-\${TAILSCALE_IP}}#g" -e "s#\${HOME}#$HOME#g" "$plist_src" >"$rendered"
    if grep -q '<string>REDACTED</string>' "$rendered"; then
      log "plan: rendered plist still carries REDACTED values (keys were secrets on the authoring seat)."
      log "      Fill them on this host from Keychain in $rendered before bootstrap; import will not write secrets."
      [[ $apply == 1 ]] && die "import --apply refused: REDACTED values remain in $rendered" 6
    fi
    log "plan: write $plist_dst (OMNIROUTE_SERVER_HOST=${ts_ip:-\${TAILSCALE_IP}}; backup kept if one exists)"
    if [[ $apply == 1 ]]; then
      mkdir -p "$(dirname "$plist_dst")"
      [[ -f "$plist_dst" ]] && cp -a "$plist_dst" "$plist_dst.bak.before-kit-$(date -u +%Y%m%dT%H%M%SZ)"
      cp "$rendered" "$plist_dst"
      log "run : wrote $plist_dst"
    fi
    # 4. launchd (user domain, never sudo)
    local domain="gui/$(id -u)"
    run_or_print "$apply" "unload previous agent (ignored if absent)" bash -c "launchctl bootout '$domain/$PLIST_LABEL' 2>/dev/null || true"
    run_or_print "$apply" "bootstrap LaunchAgent" launchctl bootstrap "$domain" "$plist_dst" || log "      (bootstrap said no; if already loaded, kickstart follows)"
    run_or_print "$apply" "kickstart gateway" bash -c "launchctl kickstart -k '$domain/$PLIST_LABEL' 2>/dev/null || true"
  else
    log "plan: kit carries no LaunchAgent plist; install OmniRoute's LaunchAgent by hand (see docs/fleet/04-GATEWAY.md)"
  fi
  # 5. non-secret host state, only where absent
  local f base sub src dst
  for f in lane-templates-from-live.json:state phase-combo-core.v4.json:router; do
    base="${f%%:*}"
    sub="${f##*:}"
    src="$kit/host/$base"
    dst="$TE_ROOT/$sub/$base"
    [[ -f "$src" ]] || continue
    if [[ -f "$dst" ]]; then
      log "plan: $dst exists; kit copy left at $src (diff by hand, never overwrite silently)"
    else
      run_or_print "$apply" "seed $base" bash -c "mkdir -p '$(dirname "$dst")' && cp '$src' '$dst'"
    fi
  done
  # 6. fleet sync: dry-run, then prompt
  if [[ -f "$SYNC_FLEET" ]]; then
    run_or_print "$apply" "provider fleet sync (dry-run, writes nothing)" python3 "$SYNC_FLEET" || true
    if [[ $apply == 1 ]]; then
      if [[ -t 0 ]]; then
        read -r -p "Apply the fleet sync shown above? [y/N] " answer
        if [[ "$answer" == [yY] ]]; then python3 "$SYNC_FLEET" --apply; else log "run : sync --apply skipped"; fi
      else
        log "run : no TTY; run by hand when ready: python3 $SYNC_FLEET --apply"
      fi
    else
      log "plan: then, after reading the dry-run: python3 $SYNC_FLEET --apply"
    fi
  else
    log "plan: $SYNC_FLEET not found; skip fleet sync until the temperance-parallel-dispatch skill is installed"
  fi
  # 7. health + sign-in
  log "plan: curl -s -o /dev/null -w '%{http_code}\\n' http://\${TAILSCALE_IP}:$GATEWAY_PORT/healthz   (expect 200)"
  log "plan: curl -s -o /dev/null -w '%{http_code}\\n' -H \"Authorization: Bearer \$OMNIROUTE_API_KEY\" http://\${TAILSCALE_IP}:$GATEWAY_PORT/v1/models   (expect 200; 401 without a key is healthy)"
  echo
  signin_checklist
}

# ------------------------------------------------------------------------------------------ main

main() {
  local cmd="${1:-help}"; shift || true
  case "$cmd" in
    export) cmd_export "$@" ;;
    verify) cmd_verify "$@" ;;
    import) cmd_import "$@" ;;
    help|-h|--help) usage ;;
    *) usage; die "unknown command: $cmd" 2 ;;
  esac
}

main "$@"

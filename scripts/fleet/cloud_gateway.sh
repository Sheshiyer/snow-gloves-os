#!/usr/bin/env bash
# Snow Gloves cloud gateway: OmniRoute on EC2 behind Cloudflare (infra/aws-gateway, infra/cloudflare-gateway).
#
# Every command first runs scripts/fleet/cloud_guard.py, which refuses unless fleet.yaml's
# cloud_gateway block is inside its boundary AND the AWS profile / Cloudflare token resolve to the
# pinned account and zone. Values come from $SNOWGLOVES_DATA/fleet.yaml (the private data repo).
#
#   cloud_gateway.sh guard                          all guard checks, no changes
#   cloud_gateway.sh bootstrap-state                create the private, versioned, encrypted state bucket
#   cloud_gateway.sh aws <init|plan|apply|destroy|output> [tofu args]
#   cloud_gateway.sh cloudflare <init|plan|apply|destroy|output> [tofu args]
#   cloud_gateway.sh tls-refresh                    instance pulls the origin cert from SSM, reloads caddy
#   cloud_gateway.sh tailnet-join                   one-shot auth key (Keychain) -> SSM -> instance joins, key deleted
#   cloud_gateway.sh backup-now                     run the nightly backup immediately
#
# Secrets: the Cloudflare token and the Tailscale auth key are read from the macOS Keychain into
# this process only; they are never printed or written to disk.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python3}"
GUARD="$REPO/scripts/fleet/cloud_guard.py"

die() { echo "cloud_gateway: $*" >&2; exit 1; }
log() { echo "cloud_gateway: $*"; }

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

load_env() {
  local env
  env="$("$PY" "$GUARD" env)" || die "fleet.yaml cloud_gateway is out of bounds (see above)"
  eval "$env"
  export AWS_PROFILE="$SG_PROFILE" AWS_REGION="$SG_REGION"
}

guard() { "$PY" "$GUARD" check "$1" || die "guard '$1' failed; nothing was changed"; }

cf_token() {
  local t
  t="$(security find-generic-password -s "$SG_CF_KEYCHAIN" -w 2>/dev/null)" || die "no Cloudflare token in Keychain service $SG_CF_KEYCHAIN"
  export CLOUDFLARE_API_TOKEN="$t"
}

tofu_in() {  # tofu_in <stack> <tofu args...>
  local stack="$1"; shift
  command -v tofu >/dev/null || die "OpenTofu not installed (brew install opentofu)"
  TF_DATA_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/snowgloves/tofu/$SG_NAME/$stack" \
    tofu -chdir="$REPO/infra/$stack-gateway" "$@"
}

tofu_init() {
  local stack="$1"
  tofu_in "$stack" init -input=false -reconfigure \
    -backend-config="bucket=$SG_STATE_BUCKET" \
    -backend-config="key=$SG_NAME/$stack.tfstate" \
    -backend-config="region=$SG_REGION" \
    -backend-config="profile=$SG_PROFILE" \
    -backend-config="encrypt=true" \
    -backend-config="use_lockfile=true"
}

run_stack() {  # run_stack <aws|cloudflare> <action> [args]
  local stack="$1" action="${2:-}"; shift 2 || true
  case "$action" in init|plan|apply|destroy|output) ;; *) die "unknown action '$action' (init|plan|apply|destroy|output)";; esac
  if [[ "$stack" == cloudflare ]]; then guard all; cf_token; else guard aws; fi
  if [[ "$action" == init ]]; then tofu_init "$stack"; return; fi
  [[ -d "${XDG_CACHE_HOME:-$HOME/.cache}/snowgloves/tofu/$SG_NAME/$stack" ]] || tofu_init "$stack"
  if [[ "$action" == output ]]; then tofu_in "$stack" output "$@"; return; fi
  local tmp vars; tmp="$(mktemp -d)"; vars="$tmp/$stack.tfvars.json"
  trap 'rm -rf "$tmp"' RETURN
  (umask 077; "$PY" "$GUARD" tfvars "$stack" > "$vars")
  local extra=()
  if [[ "$stack" == cloudflare ]]; then
    local ip
    [[ -d "${XDG_CACHE_HOME:-$HOME/.cache}/snowgloves/tofu/$SG_NAME/aws" ]] || tofu_init aws >/dev/null
    ip="$(tofu_in aws output -raw elastic_ip 2>/dev/null)" || die "apply the aws stack first (no elastic_ip output)"
    extra+=(-var "origin_ip=$ip")
  fi
  tofu_in "$stack" "$action" -input=false -var-file="$vars" ${extra[@]+"${extra[@]}"} "$@"
}

instance_id() { tofu_in aws output -raw instance_id 2>/dev/null || die "no instance_id (apply the aws stack first)"; }

ssm_run() {  # ssm_run <command line on the instance>
  local id cmd_id status
  id="$(instance_id)"
  cmd_id="$(aws ssm send-command --instance-ids "$id" --document-name AWS-RunShellScript \
    --comment "snowgloves: $1" --parameters "commands=[\"$1\"]" --query Command.CommandId --output text)"
  log "ssm $cmd_id on $id: $1"
  for _ in $(seq 1 60); do
    status="$(aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$id" --query Status --output text 2>/dev/null || echo Pending)"
    case "$status" in Pending|InProgress|Delayed) sleep 3;; *) break;; esac
  done
  aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$id" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
  [[ "$status" == Success ]]
}

bootstrap_state() {
  guard aws
  if aws s3api head-bucket --bucket "$SG_STATE_BUCKET" 2>/dev/null; then
    log "state bucket $SG_STATE_BUCKET exists"
  else
    log "creating state bucket $SG_STATE_BUCKET in $SG_REGION"
    aws s3api create-bucket --bucket "$SG_STATE_BUCKET" \
      --create-bucket-configuration "LocationConstraint=$SG_REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$SG_STATE_BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-versioning --bucket "$SG_STATE_BUCKET" --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$SG_STATE_BUCKET" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}'
  log "state bucket ready (private, versioned, KMS-encrypted)"
}

tailnet_join() {
  guard aws
  local key
  key="$(security find-generic-password -s "$SG_TS_KEYCHAIN" -w 2>/dev/null)" \
    || die "no Tailscale auth key in Keychain service $SG_TS_KEYCHAIN (single-use, tag:gateway)"
  # value via stdin, so the key never appears in the process list
  printf '%s' "$key" | aws ssm put-parameter --name "/$SG_NAME/tailscale/authkey" --type SecureString \
    --overwrite --value file:///dev/stdin >/dev/null
  unset key
  ssm_run "/usr/local/sbin/sg-gw-tailnet"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  ""|-h|--help|help) usage ;;
  guard) "$PY" "$GUARD" check all ;;
  bootstrap-state) load_env; bootstrap_state ;;
  aws|cloudflare) load_env; run_stack "$cmd" "$@" ;;
  tls-refresh) load_env; guard aws; ssm_run "/usr/local/sbin/sg-gw-tls" ;;
  tailnet-join) load_env; tailnet_join ;;
  backup-now) load_env; guard aws; ssm_run "/usr/local/sbin/sg-gw-backup" ;;
  *) usage; die "unknown command '$cmd'" ;;
esac

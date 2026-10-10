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
#     tofu args may not set variables (-var / -var-file): every variable comes from the guard.
#     `aws destroy` first applies termination_protection=false to the instance (its own prompt),
#     then destroys; protection stays on for every other action. It needs exactly one of:
#       --keep-backups    destroy everything except the backup bucket and its settings (it stays in
#                         state, so a later `aws apply` reuses it)
#       --delete-backups  also set force_destroy on the bucket and delete every backup object/version
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

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

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

# Per-backend tofu working data. Keyed by account, profile and state bucket as well as name, so
# pointing fleet.yaml at another account can never reuse a backend initialised for the old one.
tf_dir() { echo "${XDG_CACHE_HOME:-$HOME/.cache}/snowgloves/tofu/$SG_ACCOUNT/$SG_PROFILE/$SG_STATE_BUCKET/$SG_NAME/$1"; }

tofu_in() {  # tofu_in <stack> <tofu args...>
  local stack="$1"; shift
  command -v tofu >/dev/null || die "OpenTofu not installed (brew install opentofu)"
  TF_DATA_DIR="$(tf_dir "$stack")" tofu -chdir="$REPO/infra/$stack-gateway" "$@"
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

# Variables come only from the guard's var file: a later -var / -var-file would override the
# guard-bound values (aws_profile, hostname, zone, deny_domains, ...) and step around the boundary.
reject_var_overrides() {
  local a
  for a in "$@"; do
    case "$a" in
      -var|-var=*|--var|--var=*|-var-file|-var-file=*|--var-file|--var-file=*)
        die "refusing '$a': variables come from fleet.yaml via the guard, not the command line" ;;
    esac
  done
}

run_stack() {  # run_stack <aws|cloudflare> <action> [args]
  local stack="$1" action="${2:-}"; shift 2 || true
  case "$action" in init|plan|apply|destroy|output) ;; *) die "unknown action '$action' (init|plan|apply|destroy|output)";; esac
  reject_var_overrides "$@"
  if [[ "$stack" == cloudflare ]]; then guard all; cf_token; else guard aws; fi
  if [[ "$action" == init ]]; then tofu_init "$stack"; return; fi
  [[ -d "$(tf_dir "$stack")" ]] || tofu_init "$stack"
  if [[ "$action" == output ]]; then tofu_in "$stack" output "$@"; return; fi
  local tmp vars; tmp="$(mktemp -d)"; vars="$tmp/$stack.tfvars.json"
  trap 'rm -rf "$tmp"' RETURN
  (umask 077; "$PY" "$GUARD" tfvars "$stack" > "$vars")
  local extra=()
  if [[ "$stack" == cloudflare ]]; then
    local ip
    [[ -d "$(tf_dir aws)" ]] || tofu_init aws >/dev/null
    ip="$(tofu_in aws output -raw elastic_ip 2>/dev/null)" || die "apply the aws stack first (no elastic_ip output)"
    extra+=(-var "origin_ip=$ip")
  fi
  if [[ "$stack" == aws && "$action" == destroy ]]; then
    # The instance has API termination protection; lift it (and only it) before destroying.
    # The versioned backup bucket cannot be deleted while it holds objects, so the operator decides
    # whether the backups survive.
    local backups="" approve=() pass=() a
    for a in "$@"; do
      case "$a" in
        --keep-backups|--delete-backups)
          [[ -z "$backups" || "$backups" == "$a" ]] || die "pass only one of --keep-backups / --delete-backups"
          backups="$a" ;;
        *) pass+=("$a"); [[ "$a" == -auto-approve || "$a" == --auto-approve ]] && approve=(-auto-approve) ;;
      esac
    done
    [[ -n "$backups" ]] || die "aws destroy needs --keep-backups (leave the backup bucket and its objects) or --delete-backups (delete every backup object and version)"
    extra+=(-var "termination_protection=false")
    local pre=(-target=aws_instance.gw) scope=()
    if [[ "$backups" == --delete-backups ]]; then
      extra+=(-var "backups_force_destroy=true")
      pre+=(-target=aws_s3_bucket.backups)
    else
      # Destroy every managed resource except the bucket and its settings. Nothing in the bucket
      # group depends on the rest of the stack, so targeting the others never reaches it.
      local r
      while IFS= read -r r; do
        [[ -z "$r" || "$r" == data.* ]] && continue
        [[ "$r" =~ ^aws_s3_bucket(_[a-z_]+)?\.backups$ ]] && continue
        scope+=("-target=$r")
      done < <(tofu_in aws state list)
      [[ ${#scope[@]} -gt 0 ]] || die "nothing to destroy besides the backup bucket"
      log "keeping the backup bucket and its settings; destroying ${#scope[@]} other resources"
    fi
    log "disabling termination protection on aws_instance.gw before destroy"
    tofu_in aws apply -input=false -var-file="$vars" "${extra[@]}" "${pre[@]}" ${approve[@]+"${approve[@]}"} \
      || die "could not prepare the stack for destroy; nothing was destroyed"
    tofu_in aws destroy -input=false -var-file="$vars" "${extra[@]}" ${scope[@]+"${scope[@]}"} ${pass[@]+"${pass[@]}"} \
      || die "destroy failed or was declined; termination protection is now OFF (run 'cloud_gateway.sh aws apply' to restore it)"
    return
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
    if [[ "$SG_REGION" == us-east-1 ]]; then  # S3 rejects an explicit LocationConstraint for us-east-1
      aws s3api create-bucket --bucket "$SG_STATE_BUCKET" >/dev/null
    else
      aws s3api create-bucket --bucket "$SG_STATE_BUCKET" \
        --create-bucket-configuration "LocationConstraint=$SG_REGION" >/dev/null
    fi
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
  local param="/$SG_NAME/tailscale/authkey"
  # The instance deletes the parameter when sg-gw-tailnet runs; if send-command fails, times out or
  # never reaches the instance, delete it here too so the auth key is never left behind in SSM.
  trap 'aws ssm delete-parameter --name "'"$param"'" >/dev/null 2>&1 || true' EXIT
  # value via stdin, so the key never appears in the process list
  printf '%s' "$key" | aws ssm put-parameter --name "$param" --type SecureString \
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

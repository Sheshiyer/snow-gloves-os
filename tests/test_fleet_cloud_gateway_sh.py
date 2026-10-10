"""scripts/fleet/cloud_gateway.sh offline: the guard, tofu, aws and the Keychain are stubs that log argv."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fleet" / "cloud_gateway.sh"

GUARD_STUB = """#!/bin/bash
# stands in for `python3 scripts/fleet/cloud_guard.py <cmd>`
echo "guard $*" >> "$STUB_LOG"
case "$2" in
  env) echo "SG_NAME=sg-gw SG_REGION=eu-west-3 SG_PROFILE=company SG_ACCOUNT=111122223333 \\
SG_STATE_BUCKET=sg-gw-tfstate SG_CF_KEYCHAIN=cf SG_TS_KEYCHAIN=ts SG_HOSTNAME=gw.example.com" ;;
  tfvars) echo '{"aws_profile": "company"}' ;;
esac
"""

LOGGING_STUB = """#!/bin/bash
echo "$(basename "$0") $*" >> "$STUB_LOG"
case "$(basename "$0") $*" in
  "tofu "*"output -raw instance_id"*) echo i-0123456789abcdef0 ;;
  "tofu "*"state list"*) printf '%s\\n' data.aws_caller_identity.current aws_eip.gw aws_iam_role.gw \\
      aws_instance.gw aws_s3_bucket.backups aws_s3_bucket_lifecycle_configuration.backups \\
      aws_s3_bucket_public_access_block.backups aws_s3_bucket_server_side_encryption_configuration.backups \\
      aws_s3_bucket_versioning.backups ;;
  "security "*) printf 'tskey-auth-FAKE' ;;
  "aws ssm send-command"*) [ -n "$FAIL_SEND" ] && exit 255; echo cmd-1 ;;
  "aws ssm get-command-invocation"*) echo Success ;;
esac
exit 0
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("guard-python", GUARD_STUB), ("tofu", LOGGING_STUB), ("aws", LOGGING_STUB),
                       ("security", LOGGING_STUB)):
        p = bindir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "calls.log"
    log.touch()
    return {
        "PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PYTHON": str(bindir / "guard-python"), "STUB_LOG": str(log),
    }, log


def run(env, *args, **extra):
    return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                          timeout=60)


@pytest.mark.parametrize("override", [
    ["-var", "aws_profile=personal"], ["-var=aws_profile=personal"], ["--var", "hostname=gw.personal.example"],
    ["-var-file", "/tmp/evil.tfvars.json"], ["-var-file=/tmp/evil.tfvars.json"], ["--var-file=/tmp/x.json"],
])
@pytest.mark.parametrize("stack,action", [("aws", "plan"), ("aws", "apply"), ("cloudflare", "apply"),
                                          ("aws", "destroy")])
def test_tofu_args_cannot_override_guard_bound_variables(env, stack, action, override):
    environ, log = env
    proc = run(environ, stack, action, *override)
    assert proc.returncode == 1 and "variables come from fleet.yaml" in proc.stderr
    assert f"{action} -input=false" not in log.read_text()


def test_other_tofu_args_still_pass_through(env):
    environ, log = env
    proc = run(environ, "aws", "plan", "-target=aws_eip.gw")
    assert proc.returncode == 0, proc.stderr
    plan = [line for line in log.read_text().splitlines() if " plan -input=false" in line]
    assert len(plan) == 1 and plan[0].endswith("-target=aws_eip.gw")
    assert "termination_protection" not in plan[0]


def tofu_changes(log):
    return [line for line in log.read_text().splitlines() if line.startswith("tofu ")
            and (" apply " in line or " destroy " in line or " state " in line)]


@pytest.mark.parametrize("choice", [[], ["--keep-backups", "--delete-backups"]])
def test_aws_destroy_requires_one_backup_choice(env, choice):
    environ, log = env
    proc = run(environ, "aws", "destroy", "-auto-approve", *choice)
    assert proc.returncode == 1 and "backups" in proc.stderr
    assert tofu_changes(log) == []


def test_aws_destroy_keep_backups_never_targets_the_bucket(env):
    environ, log = env
    proc = run(environ, "aws", "destroy", "--keep-backups", "-auto-approve")
    assert proc.returncode == 0, proc.stderr
    calls = [c for c in tofu_changes(log) if " state list" not in c]
    assert len(calls) == 2
    assert " apply -input=false" in calls[0] and "-var termination_protection=false" in calls[0]
    assert "-target=aws_instance.gw" in calls[0] and "-auto-approve" in calls[0]
    assert "backups_force_destroy" not in log.read_text() and "s3_bucket" not in calls[0]
    destroy = calls[1]
    assert " destroy -input=false" in destroy and "-var termination_protection=false" in destroy
    assert {"-target=aws_eip.gw", "-target=aws_iam_role.gw", "-target=aws_instance.gw"} <= set(destroy.split())
    assert "backups" not in destroy and "data." not in destroy and "--keep-backups" not in destroy
    assert "-auto-approve" in destroy


def test_aws_destroy_delete_backups_force_destroys_the_bucket_first(env):
    environ, log = env
    proc = run(environ, "aws", "destroy", "--delete-backups", "-auto-approve")
    assert proc.returncode == 0, proc.stderr
    calls = tofu_changes(log)
    assert len(calls) == 2 and " state " not in log.read_text()
    assert " apply -input=false" in calls[0] and "-var backups_force_destroy=true" in calls[0]
    assert "-target=aws_instance.gw" in calls[0] and "-target=aws_s3_bucket.backups" in calls[0]
    assert " destroy -input=false" in calls[1] and "-var backups_force_destroy=true" in calls[1]
    assert "-target=" not in calls[1] and "--delete-backups" not in calls[1]


def test_aws_apply_keeps_termination_protection(env):
    environ, log = env
    proc = run(environ, "aws", "apply")
    assert proc.returncode == 0, proc.stderr
    assert "termination_protection" not in log.read_text()


@pytest.mark.parametrize("fail_send", ["", "1"])
def test_tailnet_join_deletes_the_auth_key_parameter_on_every_path(env, fail_send):
    environ, log = env
    proc = run(environ, "tailnet-join", FAIL_SEND=fail_send)
    assert (proc.returncode != 0) == bool(fail_send), proc.stderr
    text = log.read_text()
    assert "aws ssm put-parameter --name /sg-gw/tailscale/authkey" in text
    assert "aws ssm delete-parameter --name /sg-gw/tailscale/authkey" in text
    assert text.index("put-parameter") < text.index("delete-parameter")
    assert "tskey-auth-FAKE" not in text and "tskey-auth-FAKE" not in proc.stdout + proc.stderr

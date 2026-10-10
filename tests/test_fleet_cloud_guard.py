"""scripts/fleet/cloud_guard.py offline: aws and Cloudflare calls are stubbed."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cloud_guard", ROOT / "scripts" / "fleet" / "cloud_guard.py")
cg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cg)

ACCOUNT = "111122223333"
CF_ACCOUNT = "0123456789abcdef0123456789abcdef"
ZONE_ID = "fedcba9876543210fedcba9876543210"
TOKEN = "cf-FAKE-TOKEN-0123456789"

FLEET = {
    "schema": "snowgloves.fleet.v1",
    "gateway": {"kind": "cloud", "port": 20128, "url": "https://gw.example.com", "tailnet_url": "http://cloud-gw:20128"},
    "cloud_gateway": {
        "name": "sg-gw", "region": "eu-west-3", "hostname": "gw.example.com", "zone": "example.com",
        "aws_profile": "company", "aws_account_id": ACCOUNT, "cf_account_id": CF_ACCOUNT, "cf_zone_id": ZONE_ID,
        "deny_domains": ["personal.example"], "allow_ips": ["203.0.113.7"], "access_emails": ["ops@example.com"],
    },
}


@pytest.fixture
def fleet_file(tmp_path):
    path = tmp_path / "fleet.yaml"
    path.write_text(yaml.safe_dump(FLEET), encoding="utf-8")
    return path


@pytest.fixture
def stubs(monkeypatch):
    state = {"sts_account": ACCOUNT, "zone": {"name": "example.com", "account": {"id": CF_ACCOUNT}}, "status": 200}
    monkeypatch.setattr(cg.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, timeout=30.0):
        if cmd[:3] == ["aws", "sts", "get-caller-identity"]:
            return 0, json.dumps({"Account": state["sts_account"]}), ""
        if cmd[:2] == ["security", "find-generic-password"]:
            return 0, TOKEN + "\n", ""
        return 1, "", "unexpected"

    def fake_cf_get(path, token, timeout=15.0):
        assert token == TOKEN and path == f"/zones/{ZONE_ID}"
        ok = state["status"] == 200
        return state["status"], {"success": ok, "result": state["zone"] if ok else None,
                                 "errors": [] if ok else [{"message": "Authentication error"}]}

    monkeypatch.setattr(cg, "run", fake_run)
    monkeypatch.setattr(cg, "cf_get", fake_cf_get)
    return state


def main(capsys, *argv):
    rc = cg.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_all_checks_pass_and_token_is_never_printed(fleet_file, stubs, capsys):
    rc, out = main(capsys, "--fleet", str(fleet_file), "check", "all")
    assert rc == 0, out
    assert out.count("OK  ") == 3 and TOKEN not in out


def test_wrong_aws_account_refuses(fleet_file, stubs, capsys):
    stubs["sts_account"] = "999999999999"
    rc, out = main(capsys, "--fleet", str(fleet_file), "check", "aws")
    assert rc == 1 and "refusing" in out


@pytest.mark.parametrize("zone,status,needle", [
    ({"name": "personal.example", "account": {"id": CF_ACCOUNT}}, 200, "fleet.yaml says example.com"),
    ({"name": "example.com", "account": {"id": "other"}}, 200, "belongs to account other"),
    (None, 403, "Authentication error"),
])
def test_cloudflare_zone_must_match(fleet_file, stubs, capsys, zone, status, needle):
    stubs["zone"], stubs["status"] = zone, status
    rc, out = main(capsys, "--fleet", str(fleet_file), "check", "cloudflare")
    assert rc == 1 and needle in out


def test_boundary_failure_stops_before_any_account_call(tmp_path, stubs, capsys, monkeypatch):
    bad = json.loads(json.dumps(FLEET))
    bad["cloud_gateway"]["aws_profile"] = "default"
    path = tmp_path / "fleet.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    monkeypatch.setattr(cg, "check_aws", lambda c: pytest.fail("aws must not be called"))
    rc, out = main(capsys, "--fleet", str(path), "check", "all")
    assert rc == 1 and "FAIL boundary" in out


def test_tfvars_per_stack(fleet_file, capsys):
    rc, out = main(capsys, "--fleet", str(fleet_file), "tfvars", "aws")
    aws = json.loads(out)
    assert rc == 0 and aws["aws_profile"] == "company" and aws["instance_type"] == "t4g.medium"
    assert "cf_account_id" not in aws
    rc, out = main(capsys, "--fleet", str(fleet_file), "tfvars", "cloudflare")
    cf = json.loads(out)
    assert cf["hostname"] == "gw.example.com" and cf["allow_ips"] == ["203.0.113.7"]
    assert cf["deny_domains"] == ["personal.example"]


def test_env_exports_are_shell_safe_and_secret_free(fleet_file, capsys):
    rc, out = main(capsys, "--fleet", str(fleet_file), "env")
    assert rc == 0
    lines = dict(line.removeprefix("export ").split("=", 1) for line in out.strip().splitlines())
    assert lines["SG_PROFILE"] == "company" and lines["SG_STATE_BUCKET"] == f"sg-gw-tfstate-{ACCOUNT}"
    assert lines["SG_CF_KEYCHAIN"] == "snowgloves-cloudflare" and TOKEN not in out

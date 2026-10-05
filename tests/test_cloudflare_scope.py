"""Company account/zone rejection and secret suppression for Cloudflare-only guard."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("cloudflare_scope", Path(__file__).resolve().parents[1] / "scripts/fleet/cloudflare_scope.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.fixture
def target():
    return dict(account_id="a" * 32, zone_id="b" * 32, zone="company.example", hostname="gw.company.example",
                profile="company-admin", identity="admin@company.example", profile_cwd="/tmp/company")


@pytest.mark.parametrize("field,value", [("account_id", "bad"), ("zone_id", "bad"),
    ("zone", "thoughtseed.space"), ("profile", "default"), ("profile", "personal"),
    ("hostname", "gw.personal.example"), ("hostname", "https://gw.company.example"),
    ("profile_cwd", "relative")])
def test_target_rejects_invalid_scope(target, field, value):
    target[field] = value
    with pytest.raises(guard.ScopeError):
        guard.validate_target(target)


def test_personal_identity_is_rejected_before_token_lookup(target, monkeypatch):
    calls = []
    def run(args):
        calls.append(args)
        return dict(loggedIn=True, email="personal@example.com", accounts=[{"id": target["account_id"]}])
    monkeypatch.setattr(guard, "wrangler_json", run)
    with pytest.raises(guard.ScopeError, match="identity mismatch"):
        guard.check(target)
    assert len(calls) == 1


@pytest.mark.parametrize("field,value", [("id", "c" * 32), ("name", "other.example"), ("status", "pending"), ("account", {"id": "d" * 32})])
def test_zone_must_match_all_pins(target, field, value):
    result = dict(id=target["zone_id"], name=target["zone"], status="active", account={"id": target["account_id"]})
    result[field] = value
    with pytest.raises(guard.ScopeError, match="binding mismatch"):
        guard.validate_zone(target, dict(success=True, result=result))


def test_cli_clears_inherited_credentials_and_suppresses_failed_output(monkeypatch):
    for key in guard.OVERRIDES:
        monkeypatch.setenv(key, "SYNTHETIC_SECRET")
    def run(args, **kwargs):
        assert not any(k in kwargs["env"] for k in guard.OVERRIDES)
        return SimpleNamespace(returncode=1, stdout="SYNTHETIC_SECRET", stderr="SYNTHETIC_SECRET")
    monkeypatch.setattr(guard.subprocess, "run", run)
    with pytest.raises(guard.ScopeError) as error:
        guard.wrangler_json(["auth", "token"])
    assert "SYNTHETIC_SECRET" not in str(error.value)


def test_success_uses_fixed_read_endpoint_and_never_returns_token(target, monkeypatch):
    def auth(args):
        if args[0] == "whoami":
            return dict(loggedIn=True, email=target["identity"], accounts=[{"id": target["account_id"]}])
        assert args == ["auth", "token", "--profile", target["profile"], "--json"]
        return {"token": "SYNTHETIC_SECRET"}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(dict(success=True, result=dict(id=target["zone_id"], name=target["zone"], status="active", account={"id": target["account_id"]}))).encode()
    def fetch(request, **kwargs):
        assert request.full_url == "https://api.cloudflare.com/client/v4/zones/" + target["zone_id"]
        assert request.get_method() == "GET"
        return Response()
    monkeypatch.setattr(guard, "wrangler_json", auth)
    monkeypatch.setattr(guard.urllib.request, "urlopen", fetch)
    result = guard.check(target)
    assert result["ok"] and result["resources_mutated"] is False
    assert "SYNTHETIC_SECRET" not in json.dumps(result)

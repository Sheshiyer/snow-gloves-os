"""Offline tests for scripts/fleet/gateway_client.py (no network, no real $HOME)."""
import json
import sys
import tomllib
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "fleet"))

import gateway_client as gc  # noqa: E402

FAKE = "sk-FAKEKEY0123456789abcdef"
OLD = "sk-OLDTOKEN9876543210zyxw"
HOST = "coding-mac"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_KEY", FAKE)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    # never touch the network: stub the probe
    monkeypatch.setattr(gc, "probe_health",
                        lambda root_url, timeout=3.0: (f"{root_url}/healthz", "HTTP 200 (stub)"))
    return tmp_path / "home"


def run(capsys, *argv):
    rc = gc.main(list(argv))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def set_url(home, *extra):
    return ["set-url", "--home", str(home), "--host", HOST, "--key-ref", "env:FAKE_KEY", *extra]


def surface_files(home):
    return {s: home / rel for s, rel in gc.SURFACE_PATHS.items()}


def test_dry_run_writes_nothing_and_prints_a_diff_per_surface(home, capsys):
    rc, out, _ = run(capsys, *set_url(home))
    assert rc == 0
    assert not home.exists(), "dry-run must not create any file"
    assert "dry-run" in out
    for surface in gc.SURFACES:
        assert f"--- {surface}:" in out
    assert out.count("(proposed)") == 4
    assert "[redacted]" in out


def test_apply_writes_each_surface_with_the_right_url_shape(home, capsys):
    rc, out, _ = run(capsys, *set_url(home, "--apply"))
    assert rc == 0
    files = surface_files(home)

    claude = json.loads(files["claude"].read_text())
    assert claude["env"]["ANTHROPIC_BASE_URL"] == f"http://{HOST}:20128"  # root, no /v1
    assert claude["env"]["ANTHROPIC_AUTH_TOKEN"] == FAKE

    codex_text = files["codex"].read_text()
    codex = tomllib.loads(codex_text)
    assert "model_provider" not in codex  # default provider is opt-in (--set-default-provider)
    assert codex["model_providers"]["omniroute"]["base_url"] == f"http://{HOST}:20128/v1"
    assert codex["model_providers"]["omniroute"]["env_key"] == "FAKE_KEY"
    assert gc.BLOCK_BEGIN in codex_text and gc.BLOCK_END in codex_text

    grok = tomllib.loads(files["grok"].read_text())
    assert grok["model"]["te-orchestrator"]["base_url"] == f"http://{HOST}:20128/v1"
    assert grok["model"]["te-orchestrator"]["model"] == "noesis-orchestrator"
    assert grok["model"]["te-build"]["env_key"] == ["FAKE_KEY"]

    opencode = json.loads(files["opencode"].read_text())
    assert opencode["provider"]["omniroute"]["options"]["baseURL"] == f"http://{HOST}:20128/v1"
    assert opencode["provider"]["omniroute"]["options"]["apiKey"] == "{env:FAKE_KEY}"
    assert "written" in out


def test_second_apply_is_idempotent(home, capsys):
    run(capsys, *set_url(home, "--apply"))
    before = {s: p.read_text() for s, p in surface_files(home).items()}
    rc, out, _ = run(capsys, *set_url(home, "--apply"))
    assert rc == 0
    assert out.count("note: present") == 2  # codex + grok
    after = {s: p.read_text() for s, p in surface_files(home).items()}
    assert before == after
    assert after["codex"].count("[model_providers.omniroute]") == 1
    assert after["grok"].count("[model.te-orchestrator]") == 1
    assert after["codex"].count('model_provider = "omniroute"') == 0  # default provider is opt-in
    assert list(home.rglob("*.bak.*")) == [], "unchanged files must not be backed up again"


def test_apply_backs_up_existing_files_and_keeps_unrelated_keys(home, capsys):
    files = surface_files(home)
    files["claude"].parent.mkdir(parents=True)
    files["claude"].write_text(json.dumps({"env": {"OTHER": "keep", "ANTHROPIC_AUTH_TOKEN": OLD}, "model": "x"}))
    files["codex"].parent.mkdir(parents=True)
    original_codex = 'model = "gpt-6.1-sol"\n\n[desktop]\nfoo = 1\n'
    files["codex"].write_text(original_codex)

    rc, out, _ = run(capsys, *set_url(home, "--apply"))
    assert rc == 0

    claude_baks = list(files["claude"].parent.glob("settings.json.bak.*"))
    codex_baks = list(files["codex"].parent.glob("config.toml.bak.*"))
    assert len(claude_baks) == 1 and len(codex_baks) == 1
    assert json.loads(claude_baks[0].read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == OLD
    assert codex_baks[0].read_text() == original_codex

    claude = json.loads(files["claude"].read_text())
    assert claude["env"]["OTHER"] == "keep" and claude["model"] == "x"
    assert claude["env"]["ANTHROPIC_AUTH_TOKEN"] == FAKE
    codex_text = files["codex"].read_text()
    assert 'model = "gpt-6.1-sol"' in codex_text and "[desktop]" in codex_text
    codex = tomllib.loads(codex_text)
    assert codex["desktop"]["foo"] == 1 and "model_provider" not in codex
    assert "\n\n\n" not in codex_text, "top-level insert must not leave double blank lines"


def test_status_reports_not_fleet_then_fleet(home, capsys):
    rc, out, _ = run(capsys, "status", "--home", str(home), "--host", HOST)
    assert rc == 1
    assert out.count("NOT-FLEET") == 4
    assert "probe: GET http://coding-mac:20128/healthz -> HTTP 200 (stub)" in out

    run(capsys, *set_url(home, "--apply"))
    rc, out, _ = run(capsys, "status", "--home", str(home), "--host", HOST, "--no-probe")
    assert rc == 0
    assert out.count(" FLEET ") == 4 and "NOT-FLEET" not in out
    assert "probe:" not in out


def test_key_values_never_appear_in_output(home, capsys, monkeypatch):
    files = surface_files(home)
    files["claude"].parent.mkdir(parents=True)
    files["claude"].write_text(json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": OLD}}))
    monkeypatch.setattr(gc.shutil, "which", lambda name: None)
    outputs = []
    outputs.append(run(capsys, *set_url(home)))
    outputs.append(run(capsys, *set_url(home, "--apply")))
    outputs.append(run(capsys, "status", "--home", str(home), "--host", HOST))
    outputs.append(run(capsys, "doctor", "--home", str(home), "--host", HOST, "--key-ref", "env:FAKE_KEY"))
    text = "".join(o[1] + o[2] for o in outputs)
    assert FAKE not in text
    assert OLD not in text
    assert "[redacted]" in outputs[0][1]
    assert json.loads(files["claude"].read_text())["env"]["ANTHROPIC_AUTH_TOKEN"] == FAKE


def test_doctor_reports_env_key_ref_and_tailscale(home, capsys, monkeypatch):
    monkeypatch.setattr(gc.shutil, "which", lambda name: None)
    rc, out, _ = run(capsys, "doctor", "--home", str(home), "--host", HOST, "--key-ref", "env:FAKE_KEY")
    assert "tailscale: MISSING" in out
    assert "key_ref env:FAKE_KEY: set" in out
    assert "env FAKE_KEY: set" in out
    assert rc == 1  # surfaces not pointed yet + tailscale missing

    monkeypatch.delenv("FAKE_KEY")
    rc, out, _ = run(capsys, "doctor", "--home", str(home), "--host", HOST, "--key-ref", "env:FAKE_KEY", "--no-probe")
    assert "key_ref env:FAKE_KEY: unset" in out
    assert rc == 1


def test_apply_without_resolvable_key_skips_claude_only(home, capsys, monkeypatch):
    monkeypatch.delenv("FAKE_KEY")
    rc, out, err = run(capsys, *set_url(home, "--apply"))
    assert rc == 1
    assert "skipped (key_ref did not resolve" in out
    assert not surface_files(home)["claude"].exists()
    assert surface_files(home)["codex"].exists()
    assert "did not resolve" in err


def test_opencode_literal_api_key_is_left_in_place(home, capsys):
    files = surface_files(home)
    files["opencode"].parent.mkdir(parents=True)
    files["opencode"].write_text(json.dumps({
        "enabled_providers": ["temperance"],
        "provider": {"omniroute": {"options": {"baseURL": "http://127.0.0.1:20128/v1", "apiKey": OLD},
                                   "models": {"noesis-fast": {}}}},
    }))
    rc, out, _ = run(capsys, *set_url(home, "--surfaces", "opencode", "--apply"))
    assert rc == 0
    data = json.loads(files["opencode"].read_text())
    assert data["provider"]["omniroute"]["options"]["apiKey"] == OLD
    assert data["provider"]["omniroute"]["options"]["baseURL"] == f"http://{HOST}:20128/v1"
    assert data["provider"]["omniroute"]["models"] == {"noesis-fast": {}}
    assert "omniroute" in data["enabled_providers"]
    assert "holds a literal" in out
    assert OLD not in out


def test_probe_health_is_offline_safe(monkeypatch):
    def refuse(url, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(gc.urllib.request, "urlopen", refuse)
    url, result = gc.probe_health("http://coding-mac:20128", timeout=0.1)
    assert url == "http://coding-mac:20128/healthz"
    assert result == "unreachable (URLError)"

    def unauthorized(url, timeout):
        raise urllib.error.HTTPError(url, 401, "nope", hdrs=None, fp=None)

    monkeypatch.setattr(gc.urllib.request, "urlopen", unauthorized)
    assert gc.probe_health("http://coding-mac:20128")[1] == "HTTP 401"


def test_default_host_comes_from_fleet_yaml(tmp_path, home, capsys):
    fleet = tmp_path / "fleet.yaml"
    fleet.write_text('schema: snowgloves.fleet.v1\ngateway:\n  port: 20128\n  url: "http://gw-test:20128"\n')
    rc, out, _ = run(capsys, "status", "--home", str(home), "--fleet", str(fleet), "--no-probe")
    assert "gateway: http://gw-test:20128" in out


def test_bad_key_ref_and_surface_are_rejected(home, capsys):
    with pytest.raises(SystemExit):
        gc.main(["set-url", "--home", str(home), "--host", HOST, "--key-ref", "bogus"])
    with pytest.raises(SystemExit):
        gc.main(["status", "--home", str(home), "--host", HOST, "--surfaces", "vim"])


def test_host_change_rewrites_managed_blocks(home, capsys):
    run(capsys, *set_url(home, "--apply"))
    args = [a if a != HOST else "100.64.0.10" for a in set_url(home, "--apply")]
    rc, out, _ = run(capsys, *args)
    assert rc == 0
    assert out.count("updated base_url") == 2  # codex + grok managed blocks move together
    files = surface_files(home)
    codex = tomllib.loads(files["codex"].read_text())
    assert codex["model_providers"]["omniroute"]["base_url"] == "http://100.64.0.10:20128/v1"
    grok = tomllib.loads(files["grok"].read_text())
    assert grok["model"]["te-orchestrator"]["base_url"] == "http://100.64.0.10:20128/v1"
    assert files["codex"].read_text().count("[model_providers.omniroute]") == 1


def test_set_default_provider_is_opt_in(home, capsys):
    run(capsys, *set_url(home, "--apply"))
    files = surface_files(home)
    assert 'model_provider = "omniroute"' not in files["codex"].read_text()
    rc, out, _ = run(capsys, *set_url(home, "--apply", "--set-default-provider"))
    assert rc == 0
    text = files["codex"].read_text()
    assert text.count('model_provider = "omniroute"') == 1
    rc, out, _ = run(capsys, *set_url(home, "--apply", "--set-default-provider"))
    assert files["codex"].read_text().count('model_provider = "omniroute"') == 1


# ----------------------------------------------------------------------------- cloud (https) gateway

CLOUD = "https://gw.example.com"


def test_https_url_writes_root_and_v1_without_a_port(home, capsys):
    rc, out, _ = run(capsys, "set-url", "--home", str(home), "--url", CLOUD + "/", "--key-ref", "env:FAKE_KEY", "--apply")
    assert rc == 0
    files = surface_files(home)
    assert json.loads(files["claude"].read_text())["env"]["ANTHROPIC_BASE_URL"] == CLOUD
    assert tomllib.loads(files["codex"].read_text())["model_providers"]["omniroute"]["base_url"] == CLOUD + "/v1"
    assert tomllib.loads(files["grok"].read_text())["model"]["te-fast"]["base_url"] == CLOUD + "/v1"
    assert json.loads(files["opencode"].read_text())["provider"]["omniroute"]["options"]["baseURL"] == CLOUD + "/v1"
    assert f"gateway: {CLOUD}" in out


def test_moving_from_tailnet_to_cloud_rewrites_managed_blocks_and_status_follows(home, capsys):
    run(capsys, *set_url(home, "--apply"))
    rc, out, _ = run(capsys, "set-url", "--home", str(home), "--url", CLOUD, "--key-ref", "env:FAKE_KEY", "--apply")
    assert rc == 0 and out.count("updated base_url") == 2
    rc, out, _ = run(capsys, "status", "--home", str(home), "--url", CLOUD, "--no-probe")
    assert rc == 0 and out.count(" FLEET ") == 4
    rc, out, _ = run(capsys, "status", "--home", str(home), "--host", HOST, "--no-probe")
    assert rc == 1 and out.count("NOT-FLEET") == 4


def test_is_fleet_compares_scheme_host_and_default_port():
    assert gc.is_fleet("https://gw.example.com/v1", "https://gw.example.com")
    assert gc.is_fleet("https://GW.example.com:443", "https://gw.example.com")
    assert not gc.is_fleet("http://gw.example.com/v1", "https://gw.example.com")
    assert not gc.is_fleet("https://gw.example.com:8443", "https://gw.example.com")
    assert gc.parse_gateway_url("gw.example.com") == ("http", "gw.example.com", 80)


def test_doctor_does_not_require_tailscale_for_an_https_gateway(home, capsys, monkeypatch):
    monkeypatch.setattr(gc.shutil, "which", lambda name: None)
    monkeypatch.setattr(gc.Path, "exists", lambda self: False)
    run(capsys, "set-url", "--home", str(home), "--url", CLOUD, "--key-ref", "env:FAKE_KEY", "--apply")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "x")
    rc, out, _ = run(capsys, "doctor", "--home", str(home), "--url", CLOUD, "--no-probe")
    assert "tailscale: absent (optional" in out
    assert rc == 0


def test_fleet_yaml_cloud_url_and_tailnet_fallback(tmp_path, home, capsys):
    fleet = tmp_path / "fleet.yaml"
    fleet.write_text("schema: snowgloves.fleet.v1\ngateway:\n  kind: cloud\n"
                     f'  url: "{CLOUD}"\n  tailnet_url: "http://cloud-gw"\n')
    rc, out, _ = run(capsys, "status", "--home", str(home), "--fleet", str(fleet), "--no-probe")
    assert f"gateway: {CLOUD}\n" in out
    rc, out, _ = run(capsys, "status", "--home", str(home), "--fleet", str(fleet), "--via", "tailnet", "--no-probe")
    assert "gateway: http://cloud-gw:20128" in out


def test_url_and_host_together_are_rejected(home):
    with pytest.raises(SystemExit):
        gc.main(["status", "--home", str(home), "--url", CLOUD, "--host", HOST])


@pytest.mark.parametrize("url,want", [
    ("coding-mac:8080", "gateway: http://coding-mac:8080\n"),        # no scheme, explicit port: kept
    ("http://coding-mac", "gateway: http://coding-mac:20128\n"),     # bare http host: OmniRoute default
    ("coding-mac", "gateway: http://coding-mac:20128\n"),
    ("https://gw.example.com", "gateway: https://gw.example.com\n"),  # https default port stays 443
])
def test_fleet_yaml_port_resolution(tmp_path, home, capsys, url, want):
    fleet = tmp_path / "fleet.yaml"
    fleet.write_text(f'schema: snowgloves.fleet.v1\ngateway:\n  url: "{url}"\n')
    _, out, _ = run(capsys, "status", "--home", str(home), "--fleet", str(fleet), "--no-probe")
    assert want in out

"""scripts/fleet/doctor.py against a temporary root. Offline: every probe is stubbed."""
from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fleet_doctor", ROOT / "scripts" / "fleet" / "doctor.py")
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)

ORIG_PROBE_HTTP = doctor.probe_http  # captured before the autouse fixture stubs it

FLEET = {
    "schema": "snowgloves.fleet.v1",
    "company": "Example Co",
    "overlay": "tailscale",
    "gateway": {"wing": "coding", "port": 20128, "url": "http://10.255.255.1:9"},
    "authoring_seat": {"role": "staging", "hostname": "staging-mini"},
    "wings": {
        "marketing": {"hostname": "marketing-mac", "overlay": "marketing-mac", "services": []},
        "coding": {
            "hostname": "coding-mac",
            "overlay": "coding-mac",
            "services": [{"id": "omniroute", "port": 20128}, {"id": "hermes", "port": 4100}],
        },
    },
}

NODE = {"wing": "coding", "runtimes": ["claude", "codex"], "modules": [], "mcps": {}}


def seed_root(tmp_path: Path, *, profile: bool = True, registry=("acme",), manifests=("acme",)) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    home = tmp_path / "home"
    (root / "nodes" / "coding").mkdir(parents=True)
    (root / "tenants").mkdir(parents=True)
    home.mkdir()
    (root / "fleet.yaml").write_text(yaml.safe_dump(FLEET), encoding="utf-8")
    if profile:
        (root / "nodes" / "coding" / "node.yaml").write_text(yaml.safe_dump(NODE), encoding="utf-8")
    (root / "tenants" / "_registry.yaml").write_text(
        "tenants:\n" + "".join(f"  - {s}  # {s.title()}\n" for s in registry), encoding="utf-8"
    )
    for slug in manifests:
        (root / "tenants" / slug).mkdir(parents=True, exist_ok=True)
        (root / "tenants" / slug / "MANIFEST.yaml").write_text(f"slug: {slug}\n", encoding="utf-8")
    # codex config mentions the gateway; claude config is absent; grok is not a node runtime.
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('[model_providers.gw]\nbase_url = "http://10.255.255.1:9/v1"\n', encoding="utf-8")
    return root, home


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No subprocesses, no sockets, no network: fast and deterministic on any machine."""
    monkeypatch.delenv("SNOWGLOVES_NODE", raising=False)
    monkeypatch.setattr(doctor, "detect_hostname", lambda: "coding-mac")
    monkeypatch.setattr(doctor, "run", lambda cmd, timeout=5.0: (None, "", "disabled in tests"))
    monkeypatch.setattr(doctor, "find_tailscale", lambda: None)
    monkeypatch.setattr(doctor, "probe_tcp", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(doctor, "probe_http", lambda url, timeout: (True, "http 200"))


def run_json(root: Path, home: Path, capsys, *extra: str) -> tuple[int, dict]:
    rc = doctor.main(["--root", str(root), "--home", str(home), "--json", *extra])
    checks = json.loads(capsys.readouterr().out)
    assert isinstance(checks, list)
    return rc, {c["name"]: c for c in checks}


def test_wing_json_returns_check_list(tmp_path, capsys):
    root, home = seed_root(tmp_path)
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert rc == 0
    for name in ("wing", "node-profile", "tailscale", "gateway", "remote-management", "ssh", "hermes", "tenants",
                 "runtime-claude", "runtime-codex", "runtime-grok", "runtime-opencode"):
        assert name in by, name
        assert set(by[name]) >= {"name", "ok", "detail", "critical"}
    assert by["wing"]["ok"] and "via --wing" in by["wing"]["detail"]
    assert by["node-profile"]["ok"] and by["node-profile"]["critical"]
    assert by["gateway"]["ok"] and "fleet http://10.255.255.1:9/healthz" in by["gateway"]["detail"]
    assert "local http://127.0.0.1:20128/healthz" in by["gateway"]["detail"]
    assert by["tenants"]["ok"] and "1 registered" in by["tenants"]["detail"]
    assert by["tailscale"] == {"name": "tailscale", "ok": False, "detail": "not installed", "critical": False}
    assert by["hermes"]["ok"] is False and "127.0.0.1:4100" in by["hermes"]["detail"]
    # runtimes: codex mentions the gateway, claude has no config, grok/opencode are not node runtimes
    assert by["runtime-codex"]["ok"] and "mentions gateway: yes" in by["runtime-codex"]["detail"]
    assert by["runtime-claude"]["ok"] is False and "no config" in by["runtime-claude"]["detail"]
    assert by["runtime-grok"]["ok"] and "skipped" in by["runtime-grok"]["detail"]
    # never leak file contents
    assert "base_url" not in json.dumps(by)


def test_missing_node_profile_fails(tmp_path, capsys):
    root, home = seed_root(tmp_path, profile=False)
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert rc == 1
    assert by["node-profile"]["ok"] is False and by["node-profile"]["critical"]
    assert "nodes/coding/node.yaml missing" in by["node-profile"]["detail"]
    assert by["gateway"]["ok"] and by["tenants"]["ok"]  # the only failing critical check is the profile


def test_unparseable_node_profile_fails(tmp_path, capsys):
    root, home = seed_root(tmp_path)
    (root / "nodes" / "coding" / "node.yaml").write_text("wing: [unclosed\n", encoding="utf-8")
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert rc == 1
    assert "does not parse" in by["node-profile"]["detail"]


def test_gateway_down_on_both_probes_fails(tmp_path, capsys, monkeypatch):
    root, home = seed_root(tmp_path)
    monkeypatch.setattr(doctor, "probe_http", ORIG_PROBE_HTTP)

    def boom(url, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(doctor.urllib.request, "urlopen", boom)
    rc, by = run_json(root, home, capsys, "--wing", "coding", "--gateway-timeout", "0.1")
    assert rc == 1
    assert by["gateway"]["ok"] is False and by["gateway"]["critical"]
    assert by["gateway"]["detail"].count("down") == 2


def test_gateway_local_only_is_enough(tmp_path, capsys, monkeypatch):
    root, home = seed_root(tmp_path)
    monkeypatch.setattr(doctor, "probe_http", lambda url, timeout: (url.startswith("http://127.0.0.1:"), "x"))
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert rc == 0
    assert by["gateway"]["ok"] and "fleet http://10.255.255.1:9/healthz: down" in by["gateway"]["detail"]


def test_unknown_hostname_is_warn_not_fatal(tmp_path, capsys, monkeypatch):
    root, home = seed_root(tmp_path)
    monkeypatch.setattr(doctor, "detect_hostname", lambda: "Someone's Mac mini")
    # explicit wing: hostname mismatch is a WARN, every critical check still passes
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert rc == 0
    assert by["wing"]["ok"] is False and by["wing"]["critical"] is False
    assert "does not match coding-mac" in by["wing"]["detail"]
    rc = doctor.main(["--root", str(root), "--home", str(home), "--wing", "coding"])
    out = capsys.readouterr().out
    assert rc == 0
    wing_line = next(l for l in out.splitlines() if l.strip().startswith(("OK", "WARN", "FAIL")) and " wing " in l)
    assert wing_line.strip().startswith("WARN")
    assert out.rstrip().endswith("warnings)") and "OK: critical checks pass" in out
    # no wing at all: the wing line is still WARN; only the profile check (critical) fails
    rc, by = run_json(root, home, capsys)
    assert rc == 1
    assert by["wing"]["ok"] is False and by["wing"]["critical"] is False
    assert "matches no wing" in by["wing"]["detail"]
    assert "wing unknown" in by["node-profile"]["detail"] and "available: coding" in by["node-profile"]["detail"]


def test_authoring_seat_hostname_is_named(tmp_path, capsys, monkeypatch):
    root, home = seed_root(tmp_path)
    monkeypatch.setattr(doctor, "detect_hostname", lambda: "staging-mini.local")
    rc, by = run_json(root, home, capsys)
    assert rc == 1
    assert "authoring seat" in by["wing"]["detail"]


def test_env_node_selects_wing(tmp_path, capsys, monkeypatch):
    root, home = seed_root(tmp_path)
    monkeypatch.setattr(doctor, "detect_hostname", lambda: "unrelated")
    monkeypatch.setenv("SNOWGLOVES_NODE", "coding")
    rc, by = run_json(root, home, capsys)
    assert rc == 0
    assert "via SNOWGLOVES_NODE" in by["wing"]["detail"]
    assert by["node-profile"]["ok"]


def test_hostname_resolves_wing(tmp_path, capsys):
    root, home = seed_root(tmp_path)
    rc, by = run_json(root, home, capsys)  # autouse hostname is coding-mac
    assert rc == 0
    assert by["wing"] == {"name": "wing", "ok": True, "detail": "wing=coding via hostname; hostname 'coding-mac'", "critical": False}


def test_unknown_wing_override_warns(tmp_path, capsys):
    root, home = seed_root(tmp_path)
    rc, by = run_json(root, home, capsys, "--wing", "legal")
    assert rc == 1
    assert "not a wing in fleet.yaml" in by["wing"]["detail"]
    assert "nodes/legal/node.yaml missing" in by["node-profile"]["detail"]


def test_tenant_without_manifest_fails(tmp_path, capsys):
    root, home = seed_root(tmp_path, registry=("acme", "ghost"), manifests=("acme",))
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert rc == 1
    assert by["tenants"]["ok"] is False and "ghost" in by["tenants"]["detail"]


def test_hermes_probed_on_coding_overlay_from_other_wing(tmp_path, capsys, monkeypatch):
    root, home = seed_root(tmp_path)
    (root / "nodes" / "marketing").mkdir()
    (root / "nodes" / "marketing" / "node.yaml").write_text(yaml.safe_dump({"wing": "marketing", "runtimes": []}), encoding="utf-8")
    seen = []
    monkeypatch.setattr(doctor, "probe_tcp", lambda host, port, timeout=1.0: seen.append((host, port)) or True)
    rc, by = run_json(root, home, capsys, "--wing", "marketing")
    assert rc == 0
    assert ("coding-mac", 4100) in seen
    assert by["hermes"]["ok"] and "hosted by the coding wing" in by["hermes"]["detail"]
    assert all(by[f"runtime-{r}"]["ok"] and "skipped" in by[f"runtime-{r}"]["detail"] for r in doctor.RUNTIMES)


def test_missing_fleet_yaml_is_warn_with_explicit_wing(tmp_path, capsys):
    root, home = seed_root(tmp_path)
    (root / "fleet.yaml").unlink()
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert rc == 0  # inventory missing is a WARN; the three critical checks still have evidence
    assert by["wing"]["ok"] is False and "fleet.yaml missing" in by["wing"]["detail"]
    assert "wing=coding via --wing" in by["wing"]["detail"]
    assert by["node-profile"]["ok"]
    assert "fleet: no gateway.url" in by["gateway"]["detail"]  # falls back to the local port only
    assert "local http://127.0.0.1:20128/healthz" in by["gateway"]["detail"]
    # without an explicit wing there is nothing to identify the mini with
    rc, by = run_json(root, home, capsys)
    assert rc == 1 and by["node-profile"]["ok"] is False


# ---------------------------------------------------------------- cloud gateway boundary

CLOUD_BLOCK = {
    "region": "us-east-2",
    "hostname": "gw.example.com",
    "zone": "example.com",
    "aws_profile": "company",
    "aws_account_id": "111122223333",
    "cf_account_id": "0123456789abcdef0123456789abcdef",
    "cf_zone_id": "fedcba9876543210fedcba9876543210",
    "deny_domains": ["personal.example", "personal-team"],
    "deny_aws_profiles": ["personal"],
}


def seed_cloud(tmp_path, gateway: dict | None = None, **cloud) -> tuple[Path, Path]:
    root, home = seed_root(tmp_path)
    fleet = json.loads(json.dumps(FLEET))
    fleet["gateway"] = gateway or {"kind": "cloud", "port": 20128, "url": "https://gw.example.com",
                                   "tailnet_url": "http://cloud-gw:20128"}
    fleet["cloud_gateway"] = {**CLOUD_BLOCK, **cloud}
    (root / "fleet.yaml").write_text(yaml.safe_dump(fleet), encoding="utf-8")
    return root, home


def test_boundary_is_a_quiet_pass_without_a_cloud_block(tmp_path, capsys):
    root, home = seed_root(tmp_path)
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert by["fleet-boundary"]["ok"] and by["fleet-boundary"]["critical"] is False


def test_boundary_passes_for_a_clean_cloud_gateway(tmp_path, capsys):
    root, home = seed_cloud(tmp_path)
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert by["fleet-boundary"]["ok"], by["fleet-boundary"]["detail"]
    assert by["fleet-boundary"]["critical"] and rc == 0
    assert "tailnet http://cloud-gw:20128/healthz" in by["gateway"]["detail"]


@pytest.mark.parametrize("gateway,cloud,needle", [
    (None, {"hostname": "gw.personal.example", "zone": "personal.example"}, "denied domain personal.example"),
    (None, {"hostname": "gw.other.com"}, "not under zone"),
    (None, {"aws_profile": "default"}, "aws_profile default is denied"),
    (None, {"aws_profile": "personal"}, "aws_profile personal is denied"),
    (None, {"cf_zone_id": "<cf-zone-id>"}, "cf_zone_id unset"),
    (None, {"region": ""}, "cloud_gateway.region unset"),
    (None, {"aws_account_id": 111122223333}, "must be a quoted 12-digit string"),     # unquoted in YAML
    (None, {"aws_account_id": "11112222333"}, "must be a quoted 12-digit string"),    # 11 digits
    ({"kind": "cloud", "url": "http://gw.example.com"}, {}, "must be https"),
    ({"kind": "cloud", "url": "https://gw2.example.com"}, {}, "differs from cloud_gateway.hostname"),
    ({"kind": "cloud", "url": "https://gw.example.com", "tailnet_url": "http://personal-team-gw:20128"}, {},
     "denied domain personal-team"),
    # a missing or misspelled kind must not skip the https / hostname pins
    ({"url": "http://gw.example.com"}, {}, "must be https"),
    ({"kind": "clould", "url": "https://gw2.example.com"}, {}, "differs from cloud_gateway.hostname"),
    ({"kind": "clould", "url": "https://gw.example.com"}, {}, "gateway.kind must be cloud"),
    ({"url": "https://gw.example.com"}, {}, "gateway.kind must be cloud"),
])
def test_boundary_fails_closed(tmp_path, capsys, gateway, cloud, needle):
    root, home = seed_cloud(tmp_path, gateway, **cloud)
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert by["fleet-boundary"]["ok"] is False and needle in by["fleet-boundary"]["detail"]
    assert rc == 1


def test_boundary_fails_for_an_empty_cloud_block(tmp_path, capsys):
    root, home = seed_root(tmp_path)
    fleet = json.loads(json.dumps(FLEET))
    fleet["cloud_gateway"] = {}
    (root / "fleet.yaml").write_text(yaml.safe_dump(fleet), encoding="utf-8")
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert by["fleet-boundary"]["ok"] is False and "zone unset" in by["fleet-boundary"]["detail"]
    assert rc == 1


def test_boundary_reports_a_scalar_gateway_instead_of_crashing(tmp_path, capsys):
    root, home = seed_cloud(tmp_path)
    fleet = yaml.safe_load((root / "fleet.yaml").read_text(encoding="utf-8"))
    fleet["gateway"] = "https://gw.example.com"
    (root / "fleet.yaml").write_text(yaml.safe_dump(fleet), encoding="utf-8")
    rc, by = run_json(root, home, capsys, "--wing", "coding")
    assert "fleet-boundary" in by

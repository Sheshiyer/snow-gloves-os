"""Subprocess tests for scripts/fleet/gateway_kit.sh against a fake $HOME (no secrets, no network)."""
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
KIT = REPO / "scripts" / "fleet" / "gateway_kit.sh"
FAKE_KEY = "sk-FAKE1234567890"
LEAK = "sk-ABCDEFGHIJKLMNOP"
PLIST_NAME = "com.temperance.engine.omniroute.plist"
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
\t<key>EnvironmentVariables</key>
\t<dict>
\t\t<key>OMNIROUTE_API_KEY</key>
\t\t<string>{key}</string>
\t\t<key>OMNIROUTE_SERVER_HOST</key>
\t\t<string>127.0.0.1</string>
\t\t<key>PATH</key>
\t\t<string>/opt/homebrew/bin:/usr/bin:/bin</string>
\t</dict>
\t<key>Label</key>
\t<string>com.temperance.engine.omniroute</string>
\t<key>StandardOutPath</key>
\t<string>{home}/.temperance_engine/logs/omniroute.out.log</string>
</dict>
</plist>
"""


@pytest.fixture
def fake(tmp_path):
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / ".temperance_engine" / "state").mkdir(parents=True)
    plist = home / "Library" / "LaunchAgents" / PLIST_NAME
    plist.write_text(PLIST.format(key=FAKE_KEY, home=home))
    lane = home / ".temperance_engine" / "state" / "lane-templates-from-live.json"
    lane.write_text(json.dumps({"noesis-build": {"seats": ["cursor/composer-2.5", "cheaperinference/kimi-k3"]}}))
    repo = tmp_path / "repo"
    (repo / "nodes").mkdir(parents=True)
    shutil.copy(REPO / "fleet.yaml", repo / "fleet.yaml")
    (repo / "nodes" / "coding.yaml").write_text("wing: coding\n")
    return SimpleNamespace(home=home, repo=repo, out=tmp_path / "out", tmp=tmp_path, plist=plist, lane=lane)


def kit(fake, *args):
    env = {**os.environ, "HOME": str(fake.home)}
    env.pop("TEMPERANCE_ROOT", None)
    return subprocess.run(["bash", str(KIT), *args], env=env, capture_output=True, text=True,
                          timeout=120, stdin=subprocess.DEVNULL)


def export(fake, *extra):
    r = kit(fake, "export", "--out", str(fake.out), "--repo", str(fake.repo), *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    tars = sorted(fake.out.glob("gateway-kit-*.tar.gz"))
    assert len(tars) == 1
    return tars[0]


def extract(tar, dest):
    with tarfile.open(tar) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:  # Python < 3.12
            tf.extractall(dest)
    tops = [p for p in Path(dest).iterdir() if p.is_dir()]
    assert len(tops) == 1
    return tops[0]


def retar(topdir, dest):
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(topdir, arcname=topdir.name)
    return dest


def test_export_creates_tarball_manifest_and_redacted_plist(fake):
    tar = export(fake)
    assert (fake.out / "MANIFEST.sha256").exists()
    with tarfile.open(tar) as tf:
        members = {m.name.split("/", 1)[1]: m for m in tf.getmembers() if m.isfile()}
        texts = {name: tf.extractfile(m).read().decode("utf-8") for name, m in members.items()}

    plist = texts[f"host/{PLIST_NAME}"]
    assert "<string>REDACTED</string>" in plist
    assert "<string>${TAILSCALE_IP}</string>" in plist
    assert "${HOME}/.temperance_engine/logs" in plist
    assert FAKE_KEY not in plist and "<string>127.0.0.1</string>" not in plist

    for name, text in texts.items():
        assert FAKE_KEY not in text, name
    assert "fleet.yaml" in texts and "nodes/coding.yaml" in texts
    assert "host/lane-templates-from-live.json" in texts
    providers = texts["host/providers.txt"]
    assert "cheaperinference" in providers and "cursor" in providers
    for tpl in ("claude.settings.json", "codex.config.toml", "grok.config.toml", "opencode.json"):
        assert f"client-templates/{tpl}" in texts
        assert "OMNIROUTE_API_KEY" in texts[f"client-templates/{tpl}"]
    assert "coding-mac:20128" in texts["client-templates/codex.config.toml"]
    assert "sign-in checklist" in texts["README-IMPORT.md"]

    manifest_lines = [l for l in texts["MANIFEST.sha256"].splitlines() if l.strip()]
    assert len(manifest_lines) == len(texts) - 1  # every file except the manifest itself
    assert (fake.out / "MANIFEST.sha256").read_text() == texts["MANIFEST.sha256"]


def test_tailscale_ip_flag_fills_the_plist(fake):
    tar = export(fake, "--tailscale-ip", "100.64.0.9")
    top = extract(tar, fake.tmp / "x")
    plist = (top / "host" / PLIST_NAME).read_text()
    assert "<string>100.64.0.9</string>" in plist and "${TAILSCALE_IP}" not in plist
    assert "tailscale_ip: 100.64.0.9" in (top / "host" / "KIT-INFO.txt").read_text()


def test_verify_passes_then_fails_after_tamper(fake):
    tar = export(fake)
    ok = kit(fake, "verify", str(tar))
    assert ok.returncode == 0 and "verify: OK" in ok.stdout

    top = extract(tar, fake.tmp / "x")
    with (top / "fleet.yaml").open("a") as fh:
        fh.write("tampered: true\n")
    bad = retar(top, fake.tmp / "tampered.tar.gz")
    r = kit(fake, "verify", str(bad))
    assert r.returncode != 0 and "verify: FAIL" in r.stdout and "fleet.yaml" in r.stdout

    (top / "fleet.yaml").write_text((fake.repo / "fleet.yaml").read_text())
    (top / "extra.txt").write_text("not in manifest\n")
    added = retar(top, fake.tmp / "added.tar.gz")
    r = kit(fake, "verify", str(added))
    assert r.returncode != 0 and "file set differs" in r.stdout


def test_leak_guard_aborts_export(fake):
    (fake.repo / "nodes" / "leak.yaml").write_text(f"token: {LEAK}\n")
    r = kit(fake, "export", "--out", str(fake.out), "--repo", str(fake.repo))
    assert r.returncode == 3
    assert "leak guard" in r.stderr and "nodes/leak.yaml" in r.stderr
    assert LEAK not in r.stdout + r.stderr
    assert not fake.out.exists()


def test_import_dry_run_extracts_and_prints_steps_without_writing(fake):
    tar = export(fake)
    original_plist = fake.plist.read_text()
    original_lane = fake.lane.read_text()
    r = kit(fake, "import", str(tar))
    assert r.returncode == 0, r.stdout + r.stderr
    name = tar.name[: -len(".tar.gz")]
    assert (fake.home / ".snowgloves-kit" / name / "fleet.yaml").exists()
    assert "mode: dry-run" in r.stdout
    assert "plan: write" in r.stdout and "launchctl bootstrap" in r.stdout
    assert "REDACTED values" in r.stdout
    assert "sign-in checklist" in r.stdout and "/login" in r.stdout
    assert "run :" not in r.stdout
    assert fake.plist.read_text() == original_plist
    assert fake.lane.read_text() == original_lane
    assert sorted(p.name for p in (fake.home / "Library" / "LaunchAgents").iterdir()) == [PLIST_NAME]
    assert FAKE_KEY not in r.stdout + r.stderr


def test_import_apply_refuses_without_tailscale(fake):
    tar = export(fake)
    r = kit(fake, "import", str(tar), "--apply")
    assert r.returncode != 0
    assert "Tailscale" in r.stdout + r.stderr
    assert fake.plist.read_text() == PLIST.format(key=FAKE_KEY, home=fake.home)

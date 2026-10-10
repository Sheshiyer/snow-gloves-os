import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import wire_omniroute as w  # noqa: E402

FAKE_KEY = "sk-0123456789abcdef-secret"

CLAUDE = {
    "enableWorkflows": True,
    "env": {
        "ANTHROPIC_BASE_URL": "http://coding-mac:20128",
        "ANTHROPIC_AUTH_TOKEN": FAKE_KEY,
        "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
        "ANTHROPIC_MODEL": "noesis-orchestrator",
        "KEEP_ME": "1",
    },
    "model": "noesis-orchestrator",
    "hooks": {"Stop": []},
}

CODEX = '''notify = [
    "/x/y",
    "turn-ended",
]
model_provider = "omniroute"

[desktop]
followUpQueueMode = "steer"

[model_providers.omniroute]
name = "OmniRoute"
base_url = "http://coding-mac:20128/v1"
env_key = "OLD"

[shell_environment_policy]
inherit = "core"

[shell_environment_policy.set]
ANTHROPIC_BASE_URL = "http://coding-mac:20128"
ANTHROPIC_AUTH_TOKEN = "%s"

[hooks.state."/a/hooks.json:post_tool_use:0:0"]
trusted_hash = "sha256:abc"
''' % FAKE_KEY


def test_strip_claude_global_keeps_unrelated():
    out = json.loads(w.strip_claude_global(json.dumps(CLAUDE)))
    assert out["env"] == {"KEEP_ME": "1"}
    assert "model" not in out
    assert out["enableWorkflows"] is True and out["hooks"] == {"Stop": []}


def test_strip_claude_global_leaves_foreign_gateway_alone():
    foreign = {"env": {"ANTHROPIC_BASE_URL": "https://example.test"}, "model": "opus"}
    assert json.loads(w.strip_claude_global(json.dumps(foreign))) == foreign


def test_strip_claude_global_idempotent():
    once = w.strip_claude_global(json.dumps(CLAUDE))
    assert w.strip_claude_global(once) == once


def test_edit_codex_removes_global_and_preserves_rest():
    out = w.edit_codex(CODEX)
    top_level = out.split("\n[", 1)[0]
    assert "model_provider" not in top_level
    assert "ANTHROPIC" not in out and FAKE_KEY not in out
    assert 'followUpQueueMode = "steer"' in out
    assert 'trusted_hash = "sha256:abc"' in out
    assert 'notify = [\n    "/x/y",' in out
    assert "omniroute" not in out and "env_key" not in out


def test_edit_codex_idempotent():
    once = w.edit_codex(CODEX)
    assert w.edit_codex(once) == once


def test_edit_codex_keeps_unrelated_shell_env_set():
    text = '[shell_environment_policy.set]\nFOO = "bar"\n'
    assert 'FOO = "bar"' in w.edit_codex(text)


def test_edit_codex_output_is_valid_toml():
    tomllib = pytest.importorskip("tomllib")
    parsed = tomllib.loads(w.edit_codex(CODEX))
    assert "model_provider" not in parsed and "model_providers" not in parsed


def test_combo_entries_and_catalog_shape():
    payload = {"data": [
        {"id": "gpt-x", "owned_by": "openai"},
        {"id": "noesis-b", "owned_by": "combo", "description": "B · synced 2026", "context_length": 100},
        {"id": "noesis-a", "owned_by": "combo", "description": "A", "context_length": 200},
    ]}
    rows = w.combo_entries(payload)
    assert [r["id"] for r in rows] == ["noesis-a", "noesis-b"]
    template = [{"slug": "t", "apply_patch_tool_type": "freeform", "context_window": r["context_length"]} for r in rows]
    cat = w.build_catalog(rows, template)
    assert [m["slug"] for m in cat["models"]] == ["noesis-a", "noesis-b"]
    assert all(m["visibility"] == "list" and m["apply_patch_tool_type"] == "freeform" for m in cat["models"])
    assert cat["models"][1]["description"] == "B"


def test_project_merge_and_unmerge_roundtrip():
    layer = w.claude_layer(w.DEFAULT_BASE_URL, "u")
    merged = w.merge_project_claude('{"permissions": {"allow": ["x"]}}', layer)
    data = json.loads(merged)
    assert data["env"]["ANTHROPIC_BASE_URL"] == w.DEFAULT_BASE_URL and "ANTHROPIC_AUTH_TOKEN" not in data["env"]
    assert w.KEYCHAIN_SERVICE in data["apiKeyHelper"]
    assert json.loads(w.unmerge_project_claude(merged)) == {"permissions": {"allow": ["x"]}}
    assert w.unmerge_project_claude(w.merge_project_claude("", layer)) is None


@pytest.fixture
def home(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".claude/settings.json").write_text(json.dumps(CLAUDE))
    (tmp_path / ".codex/config.toml").write_text(CODEX)
    for f in (tmp_path / ".claude/settings.json", tmp_path / ".codex/config.toml"):
        f.chmod(0o600)
    return tmp_path


def run(home, *extra, monkeypatch=None):
    return w.main(["--home", str(home), "--bin-dir", str(home / "bin"), *extra])


@pytest.fixture(autouse=True)
def _no_keychain(monkeypatch):
    monkeypatch.setattr(w, "keychain_get", lambda user: None)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)


def test_dry_run_writes_nothing_and_never_prints_key(home, capsys):
    before = {p: p.read_text() for p in home.rglob("*") if p.is_file()}
    assert run(home) == 0
    out = capsys.readouterr().out
    assert FAKE_KEY not in out and "dry run" in out
    assert {p: p.read_text() for p in home.rglob("*") if p.is_file()} == before


def test_apply_backs_up_sets_modes_and_rollback_restores(home):
    orig_claude = (home / ".claude/settings.json").read_text()
    orig_codex = (home / ".codex/config.toml").read_text()
    assert run(home, "--apply") == 0
    assert list((home / ".claude").glob("settings.json.wire-bak.*"))
    assert FAKE_KEY not in (home / ".claude/settings.json").read_text()
    assert FAKE_KEY not in (home / ".codex/config.toml").read_text()
    assert oct((home / ".codex/config.toml").stat().st_mode & 0o777) == "0o600"
    assert (home / "bin/claude-or").stat().st_mode & 0o111
    assert 'exec codex --profile omniroute' in (home / "bin/codex-or").read_text()
    assert (home / ".codex/omniroute.config.toml").exists()
    assert run(home, "--rollback") == 0
    assert (home / ".claude/settings.json").read_text() == orig_claude
    assert (home / ".codex/config.toml").read_text() == orig_codex
    assert not (home / ".claude/omniroute.settings.json").exists()
    assert not (home / ".codex/omniroute.config.toml").exists()


def test_apply_twice_is_stable(home):
    run(home, "--apply")
    snap = {p.name: p.read_text() for p in home.rglob("*") if p.is_file() and ".wire-bak." not in p.name}
    run(home, "--apply")
    assert {p.name: p.read_text() for p in home.rglob("*") if p.is_file() and ".wire-bak." not in p.name} == snap


def test_apply_with_key_writes_catalog(home, monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(w, "fetch_models", lambda base, key: {"data": [{"id": "noesis-a", "owned_by": "combo", "context_length": 200000}]})
    monkeypatch.setattr(w, "routed_template", lambda rows: [{"slug": r["id"], "context_window": 1} for r in rows])
    assert run(home, "--apply") == 0
    cat = json.loads((home / ".codex/omniroute-models.json").read_text())
    assert [m["slug"] for m in cat["models"]] == ["noesis-a"]


def test_empty_combo_list_refuses(home, monkeypatch, capsys):
    monkeypatch.setenv("OMNIROUTE_API_KEY", FAKE_KEY)
    monkeypatch.setattr(w, "fetch_models", lambda base, key: {"data": []})
    assert run(home, "--apply") == 1
    assert "refusing" in capsys.readouterr().err
    assert (home / ".codex/config.toml").read_text() == CODEX


def test_redact():
    assert FAKE_KEY not in w.redact(f"token = {FAKE_KEY}")


def test_edit_codex_only_touches_intended_keys():
    tomllib = pytest.importorskip("tomllib")
    before = tomllib.loads(CODEX)
    after = tomllib.loads(w.edit_codex(CODEX))
    for key in ("notify", "desktop", "hooks"):
        assert after[key] == before[key]
    assert after["shell_environment_policy"] == {"inherit": "core"}
    assert set(after) - set(before) == set()
    assert set(before) - set(after) == {"model_provider", "model_providers"}


def test_combo_entries_skip_auto_and_unusable_slugs():
    payload = {"data": [
        {"id": "noesis-a", "owned_by": "combo"},
        {"id": "Kimi Coding", "owned_by": "combo"},
        {"id": "auto/best-coding", "owned_by": "combo"},
    ]}
    assert [r["id"] for r in w.combo_entries(payload)] == ["noesis-a"]
    assert [r["id"] for r in w.combo_entries(payload, include_auto=True)] == ["auto/best-coding", "noesis-a"]


def test_codex_profile_file_is_valid_profile_v2_layer():
    tomllib = pytest.importorskip("tomllib")
    parsed = tomllib.loads(w.codex_profile_file(w.DEFAULT_BASE_URL, "/c/cat.json", "u"))
    assert parsed["model_provider"] == "omniroute" and parsed["model_catalog_json"] == "/c/cat.json"
    provider = parsed["model_providers"]["omniroute"]
    assert provider["base_url"] == "http://127.0.0.1:20128/v1" and provider["requires_openai_auth"] is False
    assert provider["auth"]["command"] == w.SECURITY_BIN and w.KEYCHAIN_SERVICE in provider["auth"]["args"]
    assert "profiles" not in parsed  # legacy [profiles.x] makes `codex --profile` error out

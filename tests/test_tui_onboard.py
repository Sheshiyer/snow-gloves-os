import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from lib import tui_flow as flow  # noqa: E402
import tui_onboard  # noqa: E402


def test_detect_shape():
    rows = flow.detect_agent_clis()
    names = {r["name"] for r in rows}
    assert names == {"claude", "codex", "kimi"}
    for r in rows:
        assert "binaries" in r and "prompt_runtime" in r
        assert r["installed"] is bool(r["path"])


def test_agent_mode_falls_back_without_cli(monkeypatch):
    monkeypatch.setattr(flow, "which", lambda _names: None)
    resolved = flow.resolve_mode("agent")
    assert resolved["mode"] == "tui" and resolved["fallback"] is True
    assert "no claude" in resolved["reason"]


def test_agent_mode_keeps_agent_when_cli_present(monkeypatch):
    def fake(names):
        seq = (names,) if isinstance(names, str) else names
        return "/usr/bin/claude" if "claude" in seq else None

    monkeypatch.setattr(flow, "which", fake)
    resolved = flow.resolve_mode("agent")
    assert resolved["mode"] == "agent" and resolved["fallback"] is False


def test_enable_refuses_hold_and_refuse():
    row = flow.step_enable("_demo", "openspec")
    assert row["ok"] is False
    assert "hold" in row["output"].lower() or "cannot enable" in row["output"]
    row = flow.step_enable("_demo", "agent-reach")
    assert row["ok"] is False
    assert "refuse" in row["output"].lower() or "cannot enable" in row["output"]


def test_harvest_ready(tmp_path):
    p = tmp_path / "snowgloves-harvest.md"
    assert flow.harvest_ready(p) is False
    p.write_text("")
    assert flow.harvest_ready(p) is False
    p.write_text("# Tenant\nslug: acme\n")
    assert flow.harvest_ready(p) is True


def test_headless_skip_pipeline():
    receipt = flow.run_headless({"mode": "tui", "skip": ["doctor", "smoke", "walk", "apply", "enable", "render", "graph-upgrade"]})
    assert receipt["ok"] is True
    assert receipt["steps"] == []
    assert "not started" in receipt["hermes"]


def test_cli_detect_json(capsys):
    code = tui_onboard.main(["--detect"])
    assert code in (0, 1)
    data = json.loads(capsys.readouterr().out)
    assert {c["name"] for c in data["clis"]} == {"claude", "codex", "kimi"}


def test_cli_headless_skip(capsys):
    assert tui_onboard.main(["--headless", "--skip", "doctor,smoke,walk,apply,enable,render,graph-upgrade"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["steps"] == []

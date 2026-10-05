"""scripts/approvals.py: --actor is recorded as decided_by; list is unchanged."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import approvals  # scripts/ is on sys.path via tests/conftest.py


@pytest.fixture
def queue(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(approvals, "ROOT", tmp_path)
    monkeypatch.delenv("SNOWGLOVES_ACTOR", raising=False)
    q = tmp_path / "tenants" / "acme" / "approvals"
    q.mkdir(parents=True)
    rows = [
        {"id": "t1", "status": "pending", "kind": "graph-hook-diff"},
        {"id": "t2", "status": "pending", "kind": "connector-call"},
    ]
    (q / "pending.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return q


def history(q: Path) -> list[dict]:
    f = q / "history.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def test_decide_records_actor(queue):
    out = approvals.decide("acme", "t1", "approved", "looks right", actor="founder")
    assert out["ok"] and out["ticket"]["decided_by"] == "founder"
    assert out["ticket"]["status"] == "approved" and out["ticket"]["reason"] == "looks right"
    assert history(queue)[0]["decided_by"] == "founder"
    assert [r["id"] for r in approvals.load("acme")] == ["t2"]


def test_cli_actor_flag(queue, capsys):
    approvals.main(["reject", "--tenant", "acme", "--id", "t2", "--reason", "no", "--actor", "sg-coding"])
    out = json.loads(capsys.readouterr().out)
    assert out["ticket"]["status"] == "rejected" and out["ticket"]["decided_by"] == "sg-coding"
    assert history(queue)[-1] == out["ticket"]


def test_actor_defaults_to_env(queue, capsys, monkeypatch):
    monkeypatch.setenv("SNOWGLOVES_ACTOR", "sg-marketing")
    approvals.main(["approve", "--tenant", "acme", "--id", "t1"])
    out = json.loads(capsys.readouterr().out)
    assert out["ticket"]["decided_by"] == "sg-marketing"


def test_actor_empty_when_unset(queue, capsys):
    approvals.main(["approve", "--tenant", "acme", "--id", "t1"])
    out = json.loads(capsys.readouterr().out)
    assert out["ticket"]["decided_by"] == ""


def test_unknown_ticket_untouched(queue, capsys):
    approvals.main(["approve", "--tenant", "acme", "--id", "nope", "--actor", "x"])
    out = json.loads(capsys.readouterr().out)
    assert out == {"error": "ticket not found: nope"}
    assert len(approvals.load("acme")) == 2 and not history(queue)


def test_list_unchanged(queue, capsys):
    approvals.main(["list", "--tenant", "acme", "--actor", "ignored"])
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["t1", "t2"]
    assert all("decided_by" not in r for r in rows)
    assert not history(queue)

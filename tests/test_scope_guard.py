import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.scope_guard import check, ScopeViolation, ApprovalRequired

def test_low_risk_passes():
    r = check("_demo", "gmail", "gmail.read_messages")
    assert r["ok"]

def test_high_risk_requires_approval(tmp_path, monkeypatch):
    with pytest.raises(ApprovalRequired):
        check("_demo", "gmail", "gmail.send_message", {"to":"x@y.io"})

def test_unknown_blocked():
    with pytest.raises(ScopeViolation):
        check("_demo", "gmail", "gmail.delete_universe")

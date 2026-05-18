import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.redact import redact, redact_text

def test_email():
    assert redact_text("ping me at alice@example.com") == "ping me at [email]"

def test_nested():
    out = redact({"to":"bob@x.io","items":["+1 415 555 0100"]})
    assert "[email]" in out["to"]
    assert "[phone]" in out["items"][0]

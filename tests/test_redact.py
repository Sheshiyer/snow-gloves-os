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

def test_structured_sha256_remains_verifiable_without_bypassing_pii():
    digest = "6a837878504a686b6cbbd581fc89e355066e883a7abb4a697da58e5b472229c6"
    out = redact({"source_digests": [{"sha256": digest}],
                  "artifact_sha256": digest, "contact": "+1 415 555 0100",
                  "sha256": "alice@example.com"})
    assert out["source_digests"][0]["sha256"] == digest
    assert out["artifact_sha256"] == digest
    assert out["contact"] == "[phone]"
    assert out["sha256"] == "[email]"

def test_unvalidated_digest_field_uses_normal_secret_redaction():
    out = redact({"sha256": "Bearer abcdefghijklmnopqrstuvwxyz012345"})
    assert "abcdefghijklmnopqrstuvwxyz012345" not in out["sha256"]

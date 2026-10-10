"""The TypeScript redaction in mods/sg-guard must agree with scripts/lib/redact.py on shared fixtures.

redact-fixtures.json is the source; redact-fixtures.ts (what the TS test imports) is generated from it.
Regenerate with SG_WRITE_FIXTURES=1 after editing the JSON.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.redact import redact_text  # noqa: E402

TESTS = ROOT / "mods" / "sg-guard" / "tests"
HEADER = ("// Generated from redact-fixtures.json by tests/test_sg_guard_parity.py; "
          "edit the JSON, then run that test with SG_WRITE_FIXTURES=1.\nexport default ")


def test_fixtures_match_python_redactor():
    cases = json.loads((TESTS / "redact-fixtures.json").read_text(encoding="utf-8"))
    assert len(cases) >= 8
    for case in cases:
        assert redact_text(case["input"]) == case["expected"], case["input"]


def test_typescript_copy_is_current():
    cases = json.loads((TESTS / "redact-fixtures.json").read_text(encoding="utf-8"))
    want = HEADER + json.dumps(cases, indent=1, ensure_ascii=False) + "\n"
    target = TESTS / "redact-fixtures.ts"
    if os.environ.get("SG_WRITE_FIXTURES"):
        target.write_text(want, encoding="utf-8")
    assert target.read_text(encoding="utf-8") == want

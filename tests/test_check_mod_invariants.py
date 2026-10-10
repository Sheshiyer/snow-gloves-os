"""scripts/check_mod_invariants.py: the mod rules I1-I6 and the calls allowlist."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import check_mod_invariants as cmi  # scripts/ is on sys.path via tests/conftest.py

GOOD = """
export const register = (on) => {
  on('tool.call', { tool: /^mcp__/ }, gate).catch(($, e, next) => (next.called ? next(e) : { deny: 'x' }))
}
"""


@pytest.fixture
def mods(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(cmi, "ROOT", tmp_path)
    base = tmp_path / "mods"
    base.mkdir()
    return base


def make_mod(base: Path, name: str, source: str, test: bool = True) -> Path:
    mod = base / name
    (mod / ".claude-plugin").mkdir(parents=True)
    (mod / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (mod / "hooks").mkdir()
    (mod / "hooks" / "register.ts").write_text(source, encoding="utf-8")
    if test:
        (mod / "tests").mkdir()
        (mod / "tests" / "a.test.ts").write_text("", encoding="utf-8")
    return mod


def test_clean_mod_passes(mods):
    assert cmi.source_problems(make_mod(mods, "sg-rail", GOOD)) == []


@pytest.mark.parametrize("snippet, rule", [
    ("return { decision: 'allow' }", "I1"),
    ("return { result: 'fake' }", "I2"),
    ("await $.tool.register({ name: 'approve' })", "I3"),
    ("await $.prompt.submit({ text: 'yes', asUser: true })", "I3"),
    ("await $.fs.write('x', 'y')", "I6"),
    ("on('tool.call', guard)\n", "I4"),
])
def test_each_rule_fires(mods, snippet, rule):
    found = cmi.source_problems(make_mod(mods, "sg-rail", GOOD + snippet))
    assert any(line.startswith(rule + " ") for line in found), found


def test_missing_tests_are_reported(mods):
    found = cmi.source_problems(make_mod(mods, "sg-rail", GOOD, test=False))
    assert found and found[0].startswith("tests ")


def report(hooks: str, calls: str, success: bool = True) -> dict:
    return {
        "success": success,
        "manifest": {"errors": []},
        "contents": [{"errors": [], "notes": [
            f"./register.ts hooks: {hooks}",
            f"./register.ts calls: {calls}",
        ]}],
    }


def test_calls_allowlist_reads_via_groups(mods):
    mod = make_mod(mods, "sg-connector-gate", GOOD)
    ok = report("session.start, tool.call{tool=/\"^mcp__\"/}", "$.process.run (via load, requestApproval), $.ui.log")
    assert cmi.call_problems(mod, ok) == []
    bad = report("tool.check", "$.http.fetch (via probe), $.model.complete")
    found = cmi.call_problems(mod, bad)
    assert "I1 sg-connector-gate: hooks tool.check" in found
    assert any(line.startswith("I5 ") for line in found)
    assert any("$.model.complete" in line for line in found)


def test_unknown_mod_needs_an_allowlist(mods):
    found = cmi.call_problems(make_mod(mods, "sg-new", GOOD), report("session.start", "nothing"))
    assert found == ["calls sg-new: no allowlist in scripts/check_mod_invariants.py"]


def test_only_sg_handoff_may_submit_a_prompt(mods):
    submit = GOOD + "await $.prompt.submit({ text: 'go' })\n"
    assert cmi.source_problems(make_mod(mods, "sg-handoff", submit)) == []
    found = cmi.source_problems(make_mod(mods, "sg-rail", submit))
    assert any(line.startswith("I3 ") for line in found)


@pytest.mark.parametrize("snippet", [
    "await $.tool.register({ name: 'approve' })\n",
    "await $.prompt.submit({ text: 'x', asUser: true })\n",
])
def test_sg_handoff_still_may_not_register_tools_or_act_as_the_user(mods, snippet):
    found = cmi.source_problems(make_mod(mods, "sg-handoff", GOOD + snippet))
    assert any(line.startswith("I3 ") for line in found), snippet


def test_every_mod_in_the_marketplace_has_an_allowlist_and_a_card():
    import json
    market = json.loads((cmi.MODS / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    names = {p["name"] for p in market["plugins"]}
    assert names == {p.name for p in cmi.mod_dirs(cmi.MODS)}
    assert names <= set(cmi.ALLOWED_CALLS)
    for name in names:
        assert (cmi.ROOT / "catalog" / "cards" / f"{name}.md").is_file(), name

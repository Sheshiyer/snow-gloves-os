import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_catalog as bc  # noqa: E402


CARD = """---
id: {id}
name: "{name}"
category: {category}
kind: skill
disposition: {disposition}
repo: "https://example.com/{id}"
source: "{source}"
risk: low
approval: {approval}
agents: [{agents}]
hooks: [{hooks}]
runtimes: [any]
summary: "Summary for {id}."
---

# {name}

Why and provenance.
"""


def write_card(root, cid, **kw):
    fields = dict(id=cid, name=cid.title(), category="skills", disposition="add",
                  source="2035841006273548481", approval="no", agents="interpreter",
                  hooks="interpreter.funnel-and-launch")
    fields.update(kw)
    path = root / "catalog" / "cards" / f"{cid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CARD.format(**fields), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    for slug, role in (("interpreter", "Interpretation Engine"), ("ceo", "Chief Executive Agent")):
        d = tmp_path / "agents" / slug
        d.mkdir(parents=True)
        (d / "MANIFEST.yaml").write_text(
            f'slug: {slug}\nrole: "{role}"\nlayer: {slug.upper()}\nskills: []\n', encoding="utf-8")
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "registry.yaml").write_text(
        "agents:\n  interpreter: [a, b, c]\n  ceo: [x]\n", encoding="utf-8")
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "skill-hooks.yaml").write_text(
        "routing:\n  interpreter:\n    hooks:\n      - id: funnel-and-launch\n        globs: ['*launch*']\n"
        "  ceo:\n    hooks:\n      - id: strategy-and-vision\n        globs: ['*strategy*']\n",
        encoding="utf-8")
    caps = tmp_path / "connectors" / "g-stack"
    caps.mkdir(parents=True)
    (caps / "capabilities.yaml").write_text(
        "connectors:\n  slack:\n    auth: oauth2\n    capabilities:\n"
        "      - id: slack.post_message\n        risk: medium\n        approval: required\n"
        "      - id: slack.read\n        risk: low\n",
        encoding="utf-8")
    write_card(tmp_path, "ms-cro")
    write_card(tmp_path, "awesome-mcp", category="mcp", disposition="refuse", agents="", hooks="")
    write_card(tmp_path, "fk-fundraising", category="playbook", disposition="pointer",
               agents="ceo", hooks="ceo.strategy-and-vision", approval="yes")
    return tmp_path


def test_write_then_check_clean(repo, capsys):
    assert bc.main(["--root", str(repo)]) == 0
    assert (repo / "catalog" / "registry.yaml").exists()
    assert bc.main(["--root", str(repo), "--check"]) == 0


def test_check_fails_when_missing_or_stale(repo):
    assert bc.main(["--root", str(repo), "--check"]) == 1
    bc.main(["--root", str(repo)])
    write_card(repo, "ms-pricing")
    assert bc.main(["--root", str(repo), "--check"]) == 1
    bc.main(["--root", str(repo)])
    assert bc.main(["--root", str(repo), "--check"]) == 0


def test_modules_shape(repo):
    bc.main(["--root", str(repo)])
    m = json.loads((repo / "catalog" / "modules.json").read_text())
    assert m["schema"] == "snowgloves.modules.v1"
    assert m["version"] == "0.0.0"
    assert m["adapters"] == []
    assert [a["slug"] for a in m["agents"]] == ["ceo", "interpreter"]
    interp = m["agents"][1]
    assert interp["skill_count"] == 3 and interp["hooks"] == ["funnel-and-launch"]
    assert [c["id"] for c in m["cards"]] == ["awesome-mcp", "fk-fundraising", "ms-cro"]
    by_id = {c["id"]: c for c in m["cards"]}
    assert by_id["awesome-mcp"]["enableable"] is False
    assert by_id["fk-fundraising"]["enableable"] is True
    assert by_id["fk-fundraising"]["approval"] == "yes"
    assert by_id["ms-cro"]["source"] == "2035841006273548481"
    assert m["counts"]["by_disposition"] == {"add": 1, "hold": 0, "refuse": 1, "pointer": 1}
    slack = m["connectors"][0]
    assert slack["id"] == "slack"
    assert slack["capabilities"] == [
        {"id": "slack.post_message", "risk": "medium", "approval": "yes"},
        {"id": "slack.read", "risk": "low", "approval": "no"},
    ]


def test_version_and_adapters(repo):
    (repo / "VERSION").write_text("0.2.0\n")
    ad = repo / "adapters" / "claude"
    ad.mkdir(parents=True)
    (ad / "adapter.yaml").write_text(
        "schema: snowgloves.adapter.v1\nid: claude\nname: Claude Code\nquestion_tool: AskUserQuestion\n"
        "paths:\n  skills: '{home}/.claude/skills'\ninstall: []\n", encoding="utf-8")
    m = bc.build(repo)
    assert m["version"] == "0.2.0"
    assert m["adapters"][0]["id"] == "claude"
    assert m["adapters"][0]["question_tool"] == "AskUserQuestion"


def test_deterministic(repo):
    first = bc.outputs(repo)
    second = bc.outputs(repo)
    assert first == second
    assert "timestamp" not in first[repo / "catalog" / "modules.json"]


@pytest.mark.parametrize("override,msg", [
    ({"disposition": "enable"}, "disposition"),
    ({"category": "misc"}, "category"),
    ({"agents": "nobody"}, "unknown agents"),
    ({"hooks": "interpreter.no-such-hook"}, "unknown hooks"),
    ({"approval": "maybe"}, "approval"),
])
def test_invalid_cards_exit_2(repo, override, msg, capsys):
    write_card(repo, "bad-card", **override)
    assert bc.main(["--root", str(repo)]) == 2
    assert msg in capsys.readouterr().err
    assert not (repo / "catalog" / "modules.json").exists()


def test_id_must_match_filename(repo):
    path = write_card(repo, "one")
    path.rename(path.with_name("two.md"))
    with pytest.raises(bc.CatalogError, match="does not match"):
        bc.build(repo)


def test_real_cards_validate():
    m = bc.build(REPO)
    assert m["counts"]["total"] == len(list((REPO / "catalog" / "cards").glob("*.md")))
    for card in m["cards"]:
        if card["disposition"] in ("hold", "refuse"):
            assert card["enableable"] is False

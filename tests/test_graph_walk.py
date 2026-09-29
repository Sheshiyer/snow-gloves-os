import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import graph_walk as gw  # noqa: E402
from hermes import route  # noqa: E402


def write_fx(dir: Path, name: str, body: dict) -> None:
    (dir / f"{name}.yaml").write_text(yaml.safe_dump(body, sort_keys=False))


def test_fixtures_route_to_expected_desks(tmp_path):
    out = tmp_path / "graph-walk.json"
    scratch = tmp_path / "scratch"
    receipt = gw.walk(
        fixtures_dir=REPO / "tests" / "fixtures" / "graph-walk",
        out_path=out,
        scratch=scratch,
        skills_root=REPO,
    )
    assert receipt["verdict"] == "GREEN"
    data = json.loads(out.read_text())
    assert data["verdict"] == "GREEN"
    by_id = {e["id"]: e for e in data["events"]}
    assert set(by_id) >= {
        "strategy",
        "architecture",
        "people-ops",
        "research",
        "gtm",
        "virality",
        "audit",
        "fallback",
    }
    assert by_id["strategy"]["expected"]["agent"] == "ceo"
    assert by_id["fallback"]["fallback"] is True
    assert by_id["fallback"]["silent_fallback"] is False
    assert by_id["virality"]["skills"] == []
    assert by_id["virality"]["pointers"] == []
    gtm_native = [s for s in by_id["gtm"]["skills"] if s["kind"] == "native"]
    assert any(s["skill"] == "snowgloves:gtm-brief-synthesis" and s["status"] == "ok" for s in gtm_native)
    assert {loop["unit"] for loop in data["loops"]} == set(gw.NATIVE_LOOP_UNITS)
    assert all(loop["verdict"] == "GREEN" for loop in data["loops"])


def test_silent_fallback_is_red(tmp_path):
    fx = tmp_path / "fx"
    fx.mkdir()
    write_fx(
        fx,
        "oops",
        {
            "id": "oops",
            "family": "fallback",
            "task": {"title": "xyzzy plover", "tags": [], "brief": ""},
            "expect": {"agent": "ceo", "hook": "strategy-and-vision", "fallback": False},
        },
    )
    receipt = gw.walk(
        fixtures_dir=fx,
        out_path=tmp_path / "out.json",
        scratch=tmp_path / "scratch",
        skills_root=REPO,
    )
    assert receipt["verdict"] == "RED"
    ev = receipt["events"][0]
    assert ev["silent_fallback"] is True
    assert ev["UNIT"].startswith("event:")
    assert ev["SCOPE"] == "unit"


def test_missing_native_skill_is_red(tmp_path):
    def fake_route(_task):
        return [{
            "agent": "interpreter",
            "hook": "gtm-brief-synthesis",
            "skills": ["snowgloves:does-not-exist"],
            "matched_glob": "*gtm*",
        }]

    fx = tmp_path / "fx"
    fx.mkdir()
    write_fx(
        fx,
        "gtm",
        {
            "id": "gtm",
            "family": "gtm",
            "task": {"title": "refresh gtm brief", "tags": [], "brief": ""},
            "expect": {"agent": "interpreter", "hook": "gtm-brief-synthesis", "fallback": False},
        },
    )
    receipt = gw.walk(
        fixtures_dir=fx,
        out_path=tmp_path / "out.json",
        scratch=tmp_path / "scratch",
        skills_root=tmp_path,
        route_fn=fake_route,
    )
    assert receipt["verdict"] == "RED"
    assert "missing native skill" in receipt["events"][0]["REASON"]


def test_explee_is_pointer_not_green_file(tmp_path):
    row = gw.resolve_skill("explee:explee-orchestrator", tmp_path)
    assert row["kind"] == "pointer" and row["status"] == "pointer"
    row = gw.resolve_skill("inference-sh/agent-skills@viral-campaign-ideator", tmp_path)
    assert row["kind"] == "pointer"


def test_core_hooks_do_not_wire_inference_or_explee():
    hooks = yaml.safe_load((REPO / "workflows" / "skill-hooks.yaml").read_text())
    named = []
    for desk in (hooks.get("routing") or {}).values():
        for skill in desk.get("default_skills") or []:
            named.append(skill)
        for hook in desk.get("hooks") or []:
            named.extend(hook.get("skills") or [])
    assert all(s.startswith("snowgloves:") for s in named)
    assert not any("inference-sh" in s or s.startswith("explee:") for s in named)
    registry = yaml.safe_load((REPO / "skills" / "registry.yaml").read_text())
    assert registry["totals"]["all"] == 4
    catalog = yaml.safe_load((REPO / "catalog" / "registry.yaml").read_text())
    ids = {c["id"] for c in catalog["cards"]}
    assert "inference-sh-agent-skills" in ids
    assert "explee-skills" in ids


def test_inner_loop_retries_unit_only_then_red(tmp_path):
    loop = gw.inner_loop("gtm-brief-synthesis", tmp_path / "scratch", fail_attempts=3)
    assert loop["verdict"] == "RED"
    assert loop["UNIT"] == "gtm-brief-synthesis"
    assert loop["SCOPE"] == "unit"
    assert loop["attempts"] == 3
    assert "EVIDENCE" in loop and "REASON" in loop
    recovered = gw.inner_loop("tn-seed", tmp_path / "scratch", fail_attempts=2)
    assert recovered["verdict"] == "GREEN"
    assert recovered["attempts"] == 3


def test_constraint_is_read_before_hooks():
    matches = route(
        {"title": "xyzzy plover", "tags": [], "brief": ""},
        constraints=[{
            "id": "recover-xyzzy",
            "when": {"globs": ["*xyzzy*"]},
            "then": {
                "agent": "interpreter",
                "hook": "gtm-brief-synthesis",
                "skills": ["snowgloves:gtm-brief-synthesis"],
            },
        }],
    )
    assert matches[0]["source"] == "constraint"
    assert matches[0]["hook"] == "gtm-brief-synthesis"
    assert not any(m["hook"] == "default-fallback" for m in matches)

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import graph_upgrade as gu  # noqa: E402


HOOKS = {
    "routing": {
        "interpreter": {
            "hooks": [
                {
                    "id": "narrative-and-brand",
                    "globs": ["*brand story*"],
                    "skills": ["brand-story-builder"],
                }
            ]
        },
        "ceo": {
            "hooks": [
                {
                    "id": "strategy-and-vision",
                    "globs": ["*strategy*"],
                    "skills": ["mission-vision-refiner"],
                }
            ]
        },
    }
}


def seed_root(tmp_path: Path, *, mode: str = "always-ask", enabled=None, modules=None, walk=None, fallback=0):
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "skill-hooks.yaml").write_text(yaml.safe_dump(HOOKS, sort_keys=False))
    (tmp_path / "workflows" / "constraints.yaml").write_text(
        yaml.safe_dump({"version": "1", "constraints": []}, sort_keys=False)
    )
    (tmp_path / "catalog").mkdir()
    cards = modules or [
        {
            "id": "ms-copywriting",
            "disposition": "add",
            "enableable": True,
            "hooks": ["interpreter.narrative-and-brand"],
        },
        {
            "id": "spec-kit",
            "disposition": "hold",
            "enableable": False,
            "hooks": ["ceo.strategy-and-vision"],
        },
        {
            "id": "career-ops",
            "disposition": "refuse",
            "enableable": False,
            "hooks": ["interpreter.narrative-and-brand"],
        },
        {
            "id": "vanta",
            "disposition": "pointer",
            "enableable": True,
            "hooks": [],
        },
    ]
    (tmp_path / "catalog" / "modules.json").write_text(json.dumps({"modules": cards}))
    tdir = tmp_path / "tenants" / "acme"
    (tdir / "audit").mkdir(parents=True)
    (tdir / "enabled.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "snowgloves.enabled.v1",
                "modules": enabled
                or [
                    {"id": "ms-copywriting", "disposition": "add"},
                    {"id": "spec-kit", "disposition": "hold"},
                    {"id": "career-ops", "disposition": "refuse"},
                    {"id": "vanta", "disposition": "pointer"},
                ],
            },
            sort_keys=False,
        )
    )
    (tdir / "runtime.yaml").write_text(
        yaml.safe_dump({"preferences": {"approval_mode": mode}}, sort_keys=False)
    )
    if walk is None:
        walk = {
            "schema": "snowgloves.graph-walk.v1",
            "verdict": "RED",
            "events": [
                {
                    "id": "oops",
                    "family": "strategy",
                    "task": {"title": "obscure desk phrase", "tags": [], "brief": ""},
                    "verdict": "RED",
                    "silent_fallback": True,
                    "expected": {"agent": "ceo", "hook": "strategy-and-vision"},
                    "routing": [{"agent": "chief-of-staff", "hook": "default-fallback"}],
                }
            ],
            "loops": [],
        }
    (tdir / "audit" / "graph-walk.json").write_text(json.dumps(walk))
    ag = tmp_path / "agents" / "ceo"
    ag.mkdir(parents=True)
    (ag / "EVOLUTION.md").write_text(
        "## Drift alerts (from sentinel)\n"
        f"### 2099-01-01 — sentinel sweep\n- fallback_count: {fallback}\n"
    )
    return tmp_path


def test_dry_run_proposes_constraints_and_enableable_hooks_only(tmp_path, capsys):
    seed_root(tmp_path, fallback=4)
    assert gu.main(["--root", str(tmp_path), "--tenant", "acme"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["constraints_proposed"]
    assert out["constraints_proposed"][0]["then"]["hook"] == "strategy-and-vision"
    cards = {d["card"] for d in out["hook_diffs"]}
    assert cards == {"ms-copywriting"}
    assert "spec-kit" not in cards and "career-ops" not in cards
    assert all(d["blast_radius"] == "wide" for d in out["hook_diffs"])
    assert out["reports"][0]["fallback_count"] == 4
    hooks_before = (tmp_path / "workflows" / "skill-hooks.yaml").read_text()
    constraints_before = (tmp_path / "workflows" / "constraints.yaml").read_text()
    assert yaml.safe_load(constraints_before)["constraints"] == []
    assert hooks_before == (tmp_path / "workflows" / "skill-hooks.yaml").read_text()


def test_write_applies_constraints_and_tickets_wide_hooks(tmp_path, capsys):
    seed_root(tmp_path)
    hooks_before = (tmp_path / "workflows" / "skill-hooks.yaml").read_text()
    assert gu.main(["--root", str(tmp_path), "--tenant", "acme", "--write"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is False
    cons = yaml.safe_load((tmp_path / "workflows" / "constraints.yaml").read_text())
    assert cons["constraints"]
    assert (tmp_path / "workflows" / "skill-hooks.yaml").read_text() == hooks_before
    pending = (tmp_path / "tenants" / "acme" / "approvals" / "pending.jsonl").read_text()
    ticket = json.loads(pending.splitlines()[0])
    assert ticket["kind"] == "graph-hook-diff"
    assert ticket["blast_radius"] == "wide"
    assert ticket["status"] == "pending"
    assert out["applied"]["hooks"] == "ticket"


def test_allow_graph_write_applies_hook_diff(tmp_path, capsys):
    seed_root(tmp_path, mode="allow-graph-write")
    assert gu.main(["--root", str(tmp_path), "--tenant", "acme", "--write"]) == 0
    capsys.readouterr()
    hooks = yaml.safe_load((tmp_path / "workflows" / "skill-hooks.yaml").read_text())
    skills = hooks["routing"]["interpreter"]["hooks"][0]["skills"]
    assert "ms-copywriting" in skills
    assert not (tmp_path / "tenants" / "acme" / "approvals" / "pending.jsonl").exists()


def test_hold_card_never_proposed_even_if_enabled_file_lies(tmp_path, capsys):
    seed_root(
        tmp_path,
        enabled=[{"id": "spec-kit", "disposition": "add"}],
        walk={"schema": "snowgloves.graph-walk.v1", "events": [], "loops": []},
    )
    gu.main(["--root", str(tmp_path), "--tenant", "acme"])
    out = json.loads(capsys.readouterr().out)
    assert out["hook_diffs"] == []

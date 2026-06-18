import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paperclip_bridge import create_task


def test_create_task_includes_variable_contract_in_dry_payload():
    decision = {
        "task": {
            "title": "Ship contract-aware route",
            "brand_system": {"brand_archetype": "saas-ai"},
            "visual_system": {"motion_style": "data-driven"},
        },
        "routing": [{"agent": "dispatcher", "hook": "viral", "skills": ["growth"]}],
    }

    result = create_task("cambium", decision, dry=True)

    assert result["payload"]["variable_contract"] == {
        "brand_system": {"brand_archetype": "saas-ai"},
        "visual_system": {"motion_style": "data-driven"},
    }

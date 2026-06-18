import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.contract import contract_routing_terms, extract_variable_contract


def test_extracts_nested_variable_contract_without_mutating_source():
    payload = {
        "variable_contract": {
            "brand_system": {"brand_archetype": "saas-ai"},
            "asset_plan": {"required": ["ui_screenshot"]},
        }
    }

    contract = extract_variable_contract(payload)
    contract["asset_plan"]["required"].append("pricing_table")

    assert payload["variable_contract"]["asset_plan"]["required"] == ["ui_screenshot"]


def test_extracts_direct_contract_sections():
    payload = {
        "title": "Dispatch launch work",
        "brand_system": {"positioning": "operator-first"},
        "visual_primitives": {"hero_object_type": "tactical map"},
        "brief": "Ship the page.",
    }

    assert extract_variable_contract(payload) == {
        "brand_system": {"positioning": "operator-first"},
        "visual_primitives": {"hero_object_type": "tactical map"},
    }


def test_contract_routing_terms_include_brand_visual_assets_and_sections():
    contract = {
        "brand_system": {"brand_archetype": "saas-ai", "positioning": "memory-led"},
        "visual_system": {"motion_style": "data-driven", "hero_object_type": "fractal field"},
        "asset_plan": {"required": ["ui_screenshot", "pricing_table"]},
        "section_defaults": {"ordered_sections": ["hero", "proof"]},
    }

    terms = contract_routing_terms(contract)

    assert "saas-ai" in terms
    assert "data-driven" in terms
    assert "ui_screenshot" in terms
    assert "proof" in terms

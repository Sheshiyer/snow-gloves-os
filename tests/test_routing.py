import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hermes import route, route_payload

def test_viral_routes_to_dispatcher():
    r = route({"title":"viral growth loop", "tags":[], "brief":""})
    agents = {x["agent"] for x in r}
    assert "dispatcher" in agents

def test_no_match_fallback():
    r = route({"title":"xyzzy plover", "tags":[], "brief":""})
    assert any(x["hook"]=="default-fallback" for x in r)

def test_strategy_routes_to_ceo():
    r = route({"title":"refine mission statement","tags":[],"brief":""})
    assert any(x["agent"]=="ceo" for x in r)

def test_dispatcher_preserves_visual_and_asset_contract():
    payload = {
        "title": "Build campaign routing",
        "brand_system": {"brand_archetype": "saas-ai"},
        "visual_system": {"motion_style": "data-driven"},
        "asset_plan": {"required": ["ui_screenshot", "pricing_table"]},
    }

    routed = route_payload(payload)

    assert routed["variable_contract"]["brand_system"]["brand_archetype"] == "saas-ai"
    assert routed["variable_contract"]["asset_plan"]["required"] == ["ui_screenshot", "pricing_table"]

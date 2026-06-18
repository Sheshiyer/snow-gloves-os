"""Variable-contract preservation helpers for Snow Gloves routing."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


DIRECT_CONTRACT_KEYS = {
    "brand_system",
    "copy_system",
    "visual_system",
    "visual_primitives",
    "asset_plan",
    "asset_requirements",
    "section_plan",
    "section_defaults",
    "interaction_plan",
    "acceptance_checks",
}


def extract_variable_contract(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return the full Cambium variable contract without flattening it."""
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("variable_contract") or payload.get("downstream_variable_contract")
    if isinstance(nested, dict):
        return deepcopy(nested)
    return {key: deepcopy(payload[key]) for key in DIRECT_CONTRACT_KEYS if key in payload}


def contract_routing_terms(contract: dict[str, Any] | None) -> list[str]:
    """Extract route-relevant terms while keeping the original contract attached."""
    if not isinstance(contract, dict):
        return []
    brand = contract.get("brand_system", {}) if isinstance(contract.get("brand_system"), dict) else {}
    visual = contract.get("visual_system") or contract.get("visual_primitives") or {}
    if not isinstance(visual, dict):
        visual = {}
    assets = contract.get("asset_plan") or contract.get("asset_requirements") or {}
    if not isinstance(assets, dict):
        assets = {}
    sections = contract.get("section_defaults", {}) if isinstance(contract.get("section_defaults"), dict) else {}
    values: list[Any] = [
        brand.get("brand_archetype"),
        brand.get("positioning"),
        visual.get("motion_style"),
        visual.get("hero_object_type"),
        assets.get("section_type"),
        assets.get("required"),
        sections.get("ordered_sections"),
    ]
    terms: list[str] = []
    for value in values:
        if isinstance(value, list):
            terms.extend(str(item) for item in value if item)
        elif value:
            terms.append(str(value))
    return terms

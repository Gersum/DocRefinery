import os
from functools import lru_cache
from typing import Any, Dict, Optional

import yaml


DEFAULT_RULES: Dict[str, Any] = {
    "extraction_thresholds": {
        "strategy_a_min_chars": 100,
        "strategy_a_min_char_density": 0.0007,
        "strategy_a_max_image_ratio": 0.50,
        "strategy_a_font_presence_floor": 0.60,
        "escalation_confidence_gate": 0.85,
        "vision_budget_cap_usd": 1.00,
        "vision_min_remaining_budget_for_call": 0.01,
        "origin_scanned_char_density_max": 0.0008,
        "origin_digital_char_density_min": 0.0020,
        "origin_scanned_image_ratio_min": 0.50,
        "origin_form_fillable_widget_ratio_min": 0.10,
        "layout_multi_column_ratio_min": 0.20,
        "layout_multi_column_count_min": 2,
        "layout_table_page_ratio_min": 0.15,
        "layout_figure_page_ratio_min": 0.20,
        "layout_min_chars_per_page": 120,
        "layout_min_char_density": 0.0007,
        "layout_max_image_ratio": 0.75,
        "strategy_b_base_cost_usd": 0.005,
        "strategy_b_cost_per_page_usd": 0.0015,
        "layout_max_pages_per_document": 80,
        "vision_max_pages_per_document": 8,
    },
    "chunking_constitution": {},
    "retrieval_preferences": {},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=4)
def load_rules(rules_path: Optional[str] = None) -> Dict[str, Any]:
    path = rules_path or os.getenv("REFINERY_RULES_PATH", "rubric/extraction_rules.yaml")
    if not os.path.exists(path):
        return DEFAULT_RULES

    with open(path, "r", encoding="utf-8") as handle:
        parsed = yaml.safe_load(handle) or {}
    return _deep_merge(DEFAULT_RULES, parsed)


def extraction_threshold(name: str, default: Optional[Any] = None, rules_path: Optional[str] = None) -> Any:
    rules = load_rules(rules_path)
    return rules.get("extraction_thresholds", {}).get(name, default)

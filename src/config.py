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
        "strategy_a_confidence_gate": 0.85,
        "strategy_b_confidence_gate": 0.85,
        "strategy_c_review_floor": 0.75,
        "vision_budget_cap_usd": 1.00,
        "vision_min_remaining_budget_for_call": 0.01,
        "origin_scanned_char_density_max": 0.0008,
        "origin_digital_char_density_min": 0.0020,
        "origin_scanned_image_ratio_min": 0.50,
        "origin_mixed_image_ratio_min": 0.20,
        "origin_digital_chars_floor": 80,
        "origin_digital_chars_with_font_floor": 150,
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
        "language_amharic_ratio_threshold": 0.05,
        "language_confidence_floor": 0.60,
        "language_confidence_base": 0.60,
    },
    "domain_keywords": {
        "financial": ["fiscal", "revenue", "tax", "balance", "financial", "profit", "expense"],
        "legal": ["court", "judge", "plaintiff", "defendant", "auditor", "compliance"],
        "technical": ["architecture", "api", "server", "protocol", "system", "technical"],
        "medical": ["patient", "clinical", "hospital", "diagnosis"],
    },
    "chunking_constitution": {
        "rule_1": "A table cell is never split from its header row.",
        "rule_2": "A figure caption is always stored as metadata of its parent figure chunk.",
        "rule_3": "A numbered list is always kept as a single LDU unless it exceeds max_tokens.",
        "rule_4": "Section headers are stored as parent metadata on all child chunks within that section.",
        "rule_5": "Cross-references (e.g., 'see Table 3') are resolved and stored as chunk relationships.",
    },
    "retrieval_preferences": {"default_max_chunks": 5, "strict_provenance": True},
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

def domain_keywords(rules_path: Optional[str] = None) -> Dict[str, Any]:
    rules = load_rules(rules_path)
    return rules.get("domain_keywords", {})


def domain_keyword_map(rules_path: Optional[str] = None) -> Dict[str, list[str]]:
    rules = load_rules(rules_path)
    mapping = rules.get("domain_keywords", {}) or {}
    normalized: Dict[str, list[str]] = {}
    for domain, words in mapping.items():
        if not isinstance(words, list):
            continue
        normalized[str(domain).lower()] = [str(word).lower() for word in words if str(word).strip()]
    return normalized

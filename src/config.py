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
        "strategy_a_image_penalty_span": 0.50,
        "strategy_a_weight_char_signal": 0.35,
        "strategy_a_weight_density_signal": 0.30,
        "strategy_a_weight_image_signal": 0.20,
        "strategy_a_weight_font_signal": 0.15,
        "strategy_a_scan_image_ratio_floor": 0.80,
        "strategy_a_scan_char_multiplier": 0.30,
        "strategy_a_scan_confidence_cap": 0.20,
        "escalation_confidence_gate": 0.85,
        "strategy_a_confidence_gate": 0.85,
        "strategy_b_confidence_gate": 0.85,
        "strategy_c_confidence_gate": 0.85,
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
        "strategy_b_font_signal_floor": 0.25,
        "strategy_b_image_penalty_span": 0.50,
        "strategy_b_weight_char_signal": 0.30,
        "strategy_b_weight_density_signal": 0.25,
        "strategy_b_weight_image_signal": 0.20,
        "strategy_b_weight_font_signal": 0.15,
        "strategy_b_weight_structure_signal": 0.10,
        "strategy_b_structure_figure_cap": 2,
        "strategy_b_structure_norm": 3.0,
        "strategy_b_scan_image_ratio_floor": 0.80,
        "strategy_b_scan_char_multiplier": 0.50,
        "strategy_b_scan_confidence_cap": 0.45,
        "strategy_b_base_cost_usd": 0.005,
        "strategy_b_cost_per_page_usd": 0.0015,
        "layout_max_pages_per_document": 80,
        "vision_max_pages_per_document": 8,
        "strategy_c_base_confidence": 0.25,
        "strategy_c_text_confidence": 0.65,
        "strategy_c_table_confidence": 0.75,
        "strategy_c_vlm_success_confidence_with_text": 0.90,
        "strategy_c_vlm_success_confidence_without_text": 0.55,
        "strategy_c_budget_exhausted_confidence_cap": 0.85,
        "strategy_c_render_resolution_dpi": 120,
        "strategy_c_token_cost_per_token_usd": 0.000002,
        "strategy_c_request_timeout_sec": 60,
        "layout_min_words_for_column_detection": 40,
        "layout_column_left_split_factor": 0.95,
        "layout_column_right_split_factor": 1.05,
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
    "retrieval_preferences": {
        "default_max_chunks": 5,
        "strict_provenance": True,
        "chunk_max_tokens": 400,
        "pageindex_top_k": 3,
        "vector_top_k": 5,
        "similarity_min_score": 0.05,
        "embedding_dimension": 256,
        "vector_backend": "local_hash",
        "vector_chroma_path": ".refinery/chroma",
        "vector_chroma_collection": "ldus",
        "summary_max_chars": 260,
        "summary_model": "openrouter/auto",
        "summary_request_timeout_sec": 30,
        "summary_temperature": 0.0,
        "summary_max_tokens": 80,
        "fact_table_db_path": ".refinery/facts.db",
        "fact_min_numeric_length": 1,
    },
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


def chunking_constitution(rules_path: Optional[str] = None) -> Dict[str, str]:
    rules = load_rules(rules_path)
    const = rules.get("chunking_constitution", {}) or {}
    return {str(k): str(v) for k, v in const.items()}


def retrieval_preference(name: str, default: Optional[Any] = None, rules_path: Optional[str] = None) -> Any:
    rules = load_rules(rules_path)
    return rules.get("retrieval_preferences", {}).get(name, default)

import json
import os
import time
from typing import Dict, Optional

from src.config import extraction_threshold
from src.models.profile import DocumentProfile, CostEstimate
from src.models.extraction import ExtractedDocument
from src.strategies.base import BaseExtractionStrategy
from src.strategies.fast_text import FastTextExtractor
from src.strategies.layout import LayoutExtractor
from src.strategies.vision import VisionExtractor


class ExtractionRouter:
    """Routes documents to the appropriate extraction strategy with Confidence-Gated Escalation."""

    def __init__(self, ledger_path: str = ".refinery/extraction_ledger.jsonl", rules_path: Optional[str] = None):
        self.strategies: Dict[str, BaseExtractionStrategy] = {
            "strategy_a": FastTextExtractor(rules_path=rules_path),
            "strategy_b": LayoutExtractor(rules_path=rules_path),
            "strategy_c": VisionExtractor(rules_path=rules_path),
        }
        self.ledger_path = ledger_path
        self.default_threshold = float(extraction_threshold("escalation_confidence_gate", 0.85, rules_path))
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)

    def execute_extraction(self, file_path: str, profile: DocumentProfile, threshold: Optional[float] = None) -> ExtractedDocument:
        threshold_to_use = self.default_threshold if threshold is None else threshold
        strategy_key = self._select_initial_strategy(profile)
        strategy_trace = []
        token_spend = 0

        extractor = self.strategies[strategy_key]
        doc = extractor.extract(file_path, profile)
        strategy_trace.append(strategy_key)
        confidence = extractor.get_confidence()
        cost = extractor.get_cost_estimate()
        token_spend += int(getattr(extractor, "get_token_spend", lambda: 0)() or 0)
        selected_strategy = strategy_key.upper()

        if confidence < threshold_to_use and strategy_key in {"strategy_a", "strategy_b"}:
            print(
                f"Escalation Guard Triggered: {strategy_key} failed confidence threshold "
                f"({confidence:.2f} < {threshold_to_use:.2f})"
            )
            if strategy_key == "strategy_a":
                strategy_key = "strategy_b"
                doc = self.strategies[strategy_key].extract(file_path, profile)
                strategy_trace.append(strategy_key)
                confidence = self.strategies[strategy_key].get_confidence()
                cost += self.strategies[strategy_key].get_cost_estimate()
                token_spend += int(getattr(self.strategies[strategy_key], "get_token_spend", lambda: 0)() or 0)
                selected_strategy = "Strategy A -> Escalated to B"

            if strategy_key == "strategy_b" and confidence < threshold_to_use:
                strategy_key = "strategy_c"
                doc = self.strategies[strategy_key].extract(file_path, profile)
                strategy_trace.append(strategy_key)
                confidence = self.strategies[strategy_key].get_confidence()
                cost += self.strategies[strategy_key].get_cost_estimate()
                token_spend += int(getattr(self.strategies[strategy_key], "get_token_spend", lambda: 0)() or 0)
                selected_strategy = "Strategy B -> Escalated to C"
        elif confidence < threshold_to_use and strategy_key == "strategy_c":
            selected_strategy = "STRATEGY_C_LOW_CONFIDENCE"

        self._record_ledger(
            profile.document_id,
            selected_strategy,
            confidence,
            cost,
            doc.total_processing_time,
            token_spend=token_spend,
            threshold=threshold_to_use,
            strategy_trace=strategy_trace,
        )
        return doc

    def _select_initial_strategy(self, profile: DocumentProfile) -> str:
        if profile.estimated_extraction_cost == CostEstimate.FAST_TEXT_SUFFICIENT:
            return "strategy_a"
        if profile.estimated_extraction_cost == CostEstimate.NEEDS_LAYOUT_MODEL:
            return "strategy_b"
        return "strategy_c"

    def _record_ledger(
        self,
        doc_id: str,
        strategy: str,
        confidence: float,
        cost: float,
        proc_time: float,
        token_spend: int = 0,
        threshold: Optional[float] = None,
        strategy_trace: Optional[list[str]] = None,
    ):
        record = {
            "timestamp": time.time(),
            "document_id": doc_id,
            "strategy_used": strategy,
            "strategy_trace": strategy_trace or [],
            "confidence_score": confidence,
            "escalation_threshold": threshold,
            "token_spend": token_spend,
            "estimated_cost_usd": cost,
            "processing_time_sec": proc_time
        }
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(record) + "\n")

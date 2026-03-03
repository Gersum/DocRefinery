import json
import os
import time
from typing import Dict, Any

from src.models.profile import DocumentProfile, CostEstimate
from src.models.extraction import ExtractedDocument
from src.strategies.base import BaseExtractionStrategy
from src.strategies.fast_text import FastTextExtractor
from src.strategies.layout import LayoutExtractor
from src.strategies.vision import VisionExtractor

class ExtractionRouter:
    """Routes documents to the appropriate extraction strategy with Confidence-Gated Escalation."""
    
    def __init__(self, ledger_path: str = ".refinery/extraction_ledger.jsonl"):
        self.strategies: Dict[str, BaseExtractionStrategy] = {
            "strategy_a": FastTextExtractor(),
            "strategy_b": LayoutExtractor(),
            "strategy_c": VisionExtractor()
        }
        self.ledger_path = ledger_path
        os.makedirs(os.path.dirname(ledger_path), exist_ok=True)

    def execute_extraction(self, file_path: str, profile: DocumentProfile, threshold: float = 0.8) -> ExtractedDocument:
        strategy_key = self._select_initial_strategy(profile)
        
        # 1. First Attempt
        extractor = self.strategies[strategy_key]
        doc = extractor.extract(file_path, profile)
        confidence = extractor.get_confidence()
        cost = extractor.get_cost_estimate()
        
        selected_strategy = strategy_key
        
        # 2. ESCALATION GUARD
        if confidence < threshold:
            print(f"Escalation Guard Triggered: {strategy_key} failed confidence threshold ({confidence:.2f} < {threshold:.2f})")
            if strategy_key == "strategy_a":
                strategy_key = "strategy_b"
                doc = self.strategies[strategy_key].extract(file_path, profile)
                confidence = self.strategies[strategy_key].get_confidence()
                cost += self.strategies[strategy_key].get_cost_estimate()
                selected_strategy = "Strategy A -> Escalated to B"
            
            if strategy_key == "strategy_b" and confidence < threshold:
                strategy_key = "strategy_c"
                doc = self.strategies[strategy_key].extract(file_path, profile)
                confidence = self.strategies[strategy_key].get_confidence()
                cost += self.strategies[strategy_key].get_cost_estimate()
                selected_strategy = "Strategy B -> Escalated to C"

        # 3. Log to Ledger
        self._record_ledger(profile.document_id, selected_strategy, confidence, cost, doc.total_processing_time)
        return doc

    def _select_initial_strategy(self, profile: DocumentProfile) -> str:
        if profile.estimated_extraction_cost == CostEstimate.FAST_TEXT_SUFFICIENT:
            return "strategy_a"
        if profile.estimated_extraction_cost == CostEstimate.NEEDS_LAYOUT_MODEL:
            return "strategy_b"
        return "strategy_c"

    def _record_ledger(self, doc_id: str, strategy: str, confidence: float, cost: float, proc_time: float):
        record = {
            "timestamp": time.time(),
            "document_id": doc_id,
            "strategy_used": strategy,
            "confidence_score": confidence,
            "estimated_cost_usd": cost,
            "processing_time_sec": proc_time
        }
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(record) + "\n")

import time
from src.strategies.base import BaseExtractionStrategy
from src.models.extraction import ExtractedDocument, ExtractedPage
from src.models.profile import DocumentProfile

class VisionExtractor(BaseExtractionStrategy):
    """Strategy C: Extracts scanned or complex pages using an external Vision LLM.
       Mocked out for the interim submission to avoid API calls without keys.
    """
    def __init__(self, max_budget: float = 0.50):
        self._last_confidence = 1.0
        self._last_cost = 0.0
        self.max_budget = max_budget

    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        start_time = time.time()
        
        # In a real environment:
        # For each page -> Convert to image -> Send to OpenRouter(gpt-4o-mini) with structured prompt
        # mapped_doc = map_vlm_json_to_extracted_document(response)
        
        # MOCK IMPLEMENTATION FOR INTERIM PROVING
        time.sleep(2) # Simulate API latency
        self._last_confidence = 0.98
        self._last_cost = min(0.15, self.max_budget) # Token API cost estimation

        # Mocking an extracted document from Vision
        pages = [ExtractedPage(page_num=1, text_blocks=[], tables=[], figures=[], confidence_score=0.98, strategy_used="Strategy C - VisionExtractor")]

        return ExtractedDocument(
            document_id=profile.document_id,
            pages=pages,
            total_processing_time=time.time() - start_time,
            total_cost=self._last_cost
        )

    def get_confidence(self) -> float:
        return self._last_confidence
    
    def get_cost_estimate(self) -> float:
        return self._last_cost

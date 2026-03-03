import time
from src.strategies.base import BaseExtractionStrategy
from src.models.extraction import ExtractedDocument, ExtractedPage
from src.models.profile import DocumentProfile

class LayoutExtractor(BaseExtractionStrategy):
    """Strategy B: Extracts complex layouts (tables/columns) using Docling/MinerU.
       Mocked out for the interim submission without requiring huge PyTorch dependencies.
    """
    def __init__(self):
        self._last_confidence = 1.0
        self._last_cost = 0.0

    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        start_time = time.time()
        
        # In a real environment:
        # doc = docling_converter.convert(file_path)
        # mapped_doc = map_docling_to_extracted_document(doc)
        
        # MOCK IMPLEMENTATION FOR INTERIM PROVING
        time.sleep(1) # Simulate layout parsing time
        self._last_confidence = 0.95
        self._last_cost = 0.01 # Compute cost estimation

        # Mocking an extracted document with tables
        pages = [ExtractedPage(page_num=1, text_blocks=[], tables=[], figures=[], confidence_score=0.95, strategy_used="Strategy B - LayoutExtractor")]

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

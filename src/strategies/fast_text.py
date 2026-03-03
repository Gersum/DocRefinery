import time
import pdfplumber
from src.strategies.base import BaseExtractionStrategy
from src.models.extraction import ExtractedDocument, ExtractedPage, ExtractedText, BoundingBox
from src.models.profile import DocumentProfile

class FastTextExtractor(BaseExtractionStrategy):
    """Strategy A: Extracts text rapidly using pdfplumber."""
    
    def __init__(self):
        self._last_confidence = 1.0
        self._last_cost = 0.0

    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        start_time = time.time()
        pages = []
        doc_confidence_sum = 0
        total_pages = 0
        
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                total_pages += 1
                text = page.extract_text() or ""
                
                # Confidence Gate Calculation:
                # 1. Page must have a minimum character stream.
                # 2. Page shouldn't be overridden by images if characters are missing
                char_count = len(text)
                img_count = len(page.images)
                
                confidence = 1.0
                if char_count < 50 and img_count > 0:
                    confidence = 0.2  # Probable scan, need escalation
                elif char_count < 100:
                    confidence = 0.5  # Poor extraction quality maybe?
                
                # BBox approximation (pdfplumber extracts words with bboxes, but for string we'll map page-wide)
                # Production code would use page.extract_words() for spatial tracing.
                blocks = []
                if text.strip():
                     blocks.append(ExtractedText(
                         text=text,
                         page_num=i+1,
                         bbox=BoundingBox(x0=0,y0=0,x1=page.width,y1=page.height)
                     ))
                
                ext_page = ExtractedPage(
                    page_num=i+1,
                    text_blocks=blocks,
                    confidence_score=confidence,
                    strategy_used="Strategy A - FastText"
                )
                pages.append(ext_page)
                doc_confidence_sum += confidence
                
        self._last_confidence = doc_confidence_sum / max(total_pages, 1)
        self._last_cost = 0.0 # CPU only
        
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

import os
from typing import Dict, Any
import pdfplumber

from src.models.profile import DocumentProfile, OriginType, LayoutComplexity, DomainHint, CostEstimate

class TriageAgent:
    """Analyzes a document to determine origin, layout, and routing strategy."""
    
    def __init__(self, sample_pages: int = 3):
        self.sample_pages = sample_pages

    def profile_document(self, file_path: str, doc_id: str) -> DocumentProfile:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        metrics = self._gather_metrics(file_path)
        
        origin = self._detect_origin(metrics)
        layout = self._detect_layout(metrics)
        domain = self._detect_domain(metrics)
        
        # Override language if Ge'ez script is detected prominently
        is_amharic = metrics.get('amharic_char_ratio', 0.0) > 0.05
        language = "am" if is_amharic else "en"
        
        cost_est = self._estimate_cost(origin, layout, is_amharic)

        return DocumentProfile(
            document_id=doc_id,
            origin_type=origin,
            layout_complexity=layout,
            language=language,
            domain_hint=domain,
            estimated_extraction_cost=cost_est,
            page_count=metrics.get('total_pages', 0)
        )

    def _gather_metrics(self, file_path: str) -> Dict[str, Any]:
        """Extracts basic statistics using pdfplumber for the first N pages."""
        try:
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)
                pages_to_sample = min(self.sample_pages, total_pages)
                
                total_chars = 0
                image_area = 0
                page_area = 0
                words = []
                
                for i in range(pages_to_sample):
                    page = pdf.pages[i]
                    text = page.extract_text() or ""
                    total_chars += len(text)
                    words.extend(text.split()[:50]) # Grab front words for domain hint
                    
                    p_area = page.width * page.height
                    page_area += p_area
                    
                    for img in page.images:
                        image_area += img.get('width', 0) * img.get('height', 0)
                
                return {
                    "total_pages": total_pages,
                    "avg_char_density": total_chars / page_area if page_area > 0 else 0,
                    "image_ratio": image_area / page_area if page_area > 0 else 0,
                    "text_sample": " ".join(words).lower(),
                    "amharic_char_ratio": self._calculate_amharic_ratio(text)
                }
        except Exception as e:
            print(f"pdfplumber failed: {e}")
            return {"total_pages": 0, "avg_char_density": 0, "image_ratio": 1.0, "text_sample": "", "amharic_char_ratio": 0.0}

    def _calculate_amharic_ratio(self, text: str) -> float:
        """Calculates proportion of text in the Ge'ez Unicode range (\u1200 - \u137F)."""
        if not text:
            return 0.0
        amharic_chars = sum(1 for c in text if '\u1200' <= c <= '\u137F')
        return amharic_chars / len(text)


    def _detect_origin(self, metrics: Dict[str, Any]) -> OriginType:
        if metrics["avg_char_density"] < 0.001 and metrics["image_ratio"] > 0.5:
            return OriginType.SCANNED_IMAGE
        elif metrics["avg_char_density"] > 0.01:
            return OriginType.NATIVE_DIGITAL
        return OriginType.MIXED

    def _detect_layout(self, metrics: Dict[str, Any]) -> LayoutComplexity:
        # A true layout test requires bbox scanning. Mocking a basic heuristic.
        text = metrics.get('text_sample', '')
        if "table" in text or "amount" in text:
            return LayoutComplexity.TABLE_HEAVY
        
        return LayoutComplexity.SINGLE_COLUMN

    def _detect_domain(self, metrics: Dict[str, Any]) -> DomainHint:
        text = metrics.get('text_sample', '')
        if any(w in text for w in ['fiscal', 'revenue', 'tax', 'balance', 'financial']):
            return DomainHint.FINANCIAL
        if any(w in text for w in ['court', 'judge', 'plaintiff', 'defendant']):
            return DomainHint.LEGAL
        if any(w in text for w in ['architecture', 'api', 'server', 'protocol']):
            return DomainHint.TECHNICAL
        return DomainHint.GENERAL

    def _estimate_cost(self, origin: OriginType, layout: LayoutComplexity, is_amharic: bool = False) -> CostEstimate:
        if origin == OriginType.SCANNED_IMAGE or is_amharic:
            return CostEstimate.NEEDS_VISION_MODEL
        if layout in [LayoutComplexity.TABLE_HEAVY, LayoutComplexity.MULTI_COLUMN, LayoutComplexity.MIXED]:
            return CostEstimate.NEEDS_LAYOUT_MODEL
        return CostEstimate.FAST_TEXT_SUFFICIENT

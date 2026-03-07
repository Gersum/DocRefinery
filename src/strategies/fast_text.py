import time
import pdfplumber

from src.config import extraction_threshold
from src.strategies.base import BaseExtractionStrategy
from src.models.extraction import (
    BoundingBox,
    ExtractedDocument,
    ExtractedPage,
    ExtractedTable,
    ExtractedText,
)
from src.models.profile import DocumentProfile


class FastTextExtractor(BaseExtractionStrategy):
    """Strategy A: Extracts text rapidly using pdfplumber."""

    def __init__(self, rules_path: str | None = None):
        self._last_confidence = 1.0
        self._last_cost = 0.0
        self.min_chars = int(extraction_threshold("strategy_a_min_chars", 100, rules_path))
        self.min_char_density = float(extraction_threshold("strategy_a_min_char_density", 0.0007, rules_path))
        self.max_image_ratio = float(extraction_threshold("strategy_a_max_image_ratio", 0.50, rules_path))
        self.font_presence_floor = float(extraction_threshold("strategy_a_font_presence_floor", 0.60, rules_path))
        self.image_penalty_span = float(extraction_threshold("strategy_a_image_penalty_span", 0.50, rules_path))
        self.weight_char_signal = float(extraction_threshold("strategy_a_weight_char_signal", 0.35, rules_path))
        self.weight_density_signal = float(extraction_threshold("strategy_a_weight_density_signal", 0.30, rules_path))
        self.weight_image_signal = float(extraction_threshold("strategy_a_weight_image_signal", 0.20, rules_path))
        self.weight_font_signal = float(extraction_threshold("strategy_a_weight_font_signal", 0.15, rules_path))
        self.scan_image_ratio_floor = float(extraction_threshold("strategy_a_scan_image_ratio_floor", 0.80, rules_path))
        self.scan_char_multiplier = float(extraction_threshold("strategy_a_scan_char_multiplier", 0.30, rules_path))
        self.scan_confidence_cap = float(extraction_threshold("strategy_a_scan_confidence_cap", 0.20, rules_path))

    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        start_time = time.time()
        pages = []
        doc_confidence_sum = 0.0
        total_pages = 0

        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                total_pages += 1
                text = page.extract_text() or ""

                char_count = len(text)
                page_area = float(page.width * page.height) if page.width and page.height else 1.0
                char_density = char_count / max(1.0, page_area)
                image_area = sum(float(img.get("width", 0) * img.get("height", 0)) for img in page.images)
                image_ratio = image_area / max(1.0, page_area)
                page_chars = getattr(page, "chars", None) or []
                has_font_metadata = bool(page_chars) and any(char.get("fontname") for char in page_chars)

                char_signal = min(1.0, char_count / max(1, self.min_chars))
                density_signal = min(1.0, char_density / max(self.min_char_density, 1e-9))
                image_signal = 1.0 if image_ratio <= self.max_image_ratio else max(
                    0.0, 1.0 - ((image_ratio - self.max_image_ratio) / max(self.image_penalty_span, 1e-9))
                )
                font_signal = 1.0 if has_font_metadata else self.font_presence_floor
                confidence = max(
                    0.0,
                    min(
                        1.0,
                        (self.weight_char_signal * char_signal)
                        + (self.weight_density_signal * density_signal)
                        + (self.weight_image_signal * image_signal)
                        + (self.weight_font_signal * font_signal),
                    ),
                )

                # Hard floor for likely scanned pages
                if image_ratio > self.scan_image_ratio_floor and char_count < int(self.min_chars * self.scan_char_multiplier):
                    confidence = min(confidence, self.scan_confidence_cap)

                blocks = []
                if text.strip():
                    blocks.append(
                        ExtractedText(
                            text=text,
                            page_num=i + 1,
                            bbox=BoundingBox(x0=0, y0=0, x1=page.width, y1=page.height),
                        )
                    )

                extracted_tables = []
                for table_index, raw_table in enumerate(page.extract_tables() or [], start=1):
                    rows = [row for row in raw_table if row and any(cell for cell in row)]
                    if len(rows) < 2:
                        continue
                    headers = [str(cell or "").strip() for cell in rows[0]]
                    data_rows = [[str(cell or "").strip() for cell in row] for row in rows[1:]]
                    extracted_tables.append(
                        ExtractedTable(
                            table_id=f"{profile.document_id}-p{i + 1}-t{table_index}",
                            page_num=i + 1,
                            headers=headers,
                            data=data_rows,
                            bbox=BoundingBox(x0=0, y0=0, x1=page.width, y1=page.height),
                        )
                    )

                ext_page = ExtractedPage(
                    page_num=i + 1,
                    text_blocks=blocks,
                    tables=extracted_tables,
                    confidence_score=confidence,
                    strategy_used="Strategy A - FastText"
                )
                pages.append(ext_page)
                doc_confidence_sum += confidence

        self._last_confidence = doc_confidence_sum / max(total_pages, 1)
        self._last_cost = 0.0

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

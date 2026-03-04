import os
from typing import Any, Dict, Optional, Protocol

import pdfplumber

from src.config import extraction_threshold
from src.models.profile import CostEstimate, DocumentProfile, DomainHint, LayoutComplexity, OriginType


class DomainClassifier(Protocol):
    def classify(self, text: str) -> DomainHint:
        ...


class KeywordDomainClassifier:
    """Simple, pluggable domain classifier strategy."""

    def classify(self, text: str) -> DomainHint:
        normalized = text.lower()
        if any(word in normalized for word in ["fiscal", "revenue", "tax", "balance", "financial", "profit", "expense"]):
            return DomainHint.FINANCIAL
        if any(word in normalized for word in ["court", "judge", "plaintiff", "defendant", "auditor", "compliance"]):
            return DomainHint.LEGAL
        if any(word in normalized for word in ["architecture", "api", "server", "protocol", "system", "technical"]):
            return DomainHint.TECHNICAL
        if any(word in normalized for word in ["patient", "clinical", "hospital", "diagnosis"]):
            return DomainHint.MEDICAL
        return DomainHint.GENERAL


class TriageAgent:
    """Analyzes a document to determine origin, layout, and routing strategy."""

    def __init__(
        self,
        sample_pages: int = 5,
        domain_classifier: Optional[DomainClassifier] = None,
        rules_path: Optional[str] = None,
    ):
        self.sample_pages = sample_pages
        self.domain_classifier = domain_classifier or KeywordDomainClassifier()
        self.scanned_density_max = float(extraction_threshold("origin_scanned_char_density_max", 0.0008, rules_path))
        self.digital_density_min = float(extraction_threshold("origin_digital_char_density_min", 0.0020, rules_path))
        self.scanned_image_ratio_min = float(extraction_threshold("origin_scanned_image_ratio_min", 0.50, rules_path))
        self.form_fillable_widget_ratio_min = float(extraction_threshold("origin_form_fillable_widget_ratio_min", 0.10, rules_path))
        self.multi_column_ratio_min = float(extraction_threshold("layout_multi_column_ratio_min", 0.20, rules_path))
        self.multi_column_count_min = int(extraction_threshold("layout_multi_column_count_min", 2, rules_path))
        self.table_page_ratio_min = float(extraction_threshold("layout_table_page_ratio_min", 0.15, rules_path))
        self.figure_page_ratio_min = float(extraction_threshold("layout_figure_page_ratio_min", 0.20, rules_path))

    def profile_document(self, file_path: str, doc_id: str) -> DocumentProfile:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        metrics = self._gather_metrics(file_path)
        origin = self._detect_origin(metrics)
        layout = self._detect_layout(metrics)
        domain = self._detect_domain(metrics)

        amharic_ratio = metrics.get("amharic_char_ratio", 0.0)
        language = "am" if amharic_ratio > 0.05 else "en"
        language_confidence = min(1.0, max(0.6, 0.6 + amharic_ratio))
        cost_est = self._estimate_cost(origin, layout, is_amharic=(language == "am"))

        return DocumentProfile(
            document_id=doc_id,
            origin_type=origin,
            layout_complexity=layout,
            language=language,
            language_confidence=language_confidence,
            domain_hint=domain,
            estimated_extraction_cost=cost_est,
            page_count=metrics.get("total_pages", 0),
        )

    def _gather_metrics(self, file_path: str) -> Dict[str, Any]:
        """Extracts routing metrics from the first N pages."""
        try:
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)
                pages_to_sample = min(self.sample_pages, total_pages)

                total_chars = 0
                total_image_area = 0.0
                total_page_area = 0.0
                words_for_domain = []
                all_sample_text = []
                table_pages = 0
                multi_column_pages = 0
                figure_pages = 0
                font_metadata_pages = 0
                widget_pages = 0
                column_count_total = 0.0

                for idx in range(pages_to_sample):
                    page = pdf.pages[idx]
                    page_text = page.extract_text() or ""
                    all_sample_text.append(page_text)
                    words_for_domain.extend(page_text.split()[:60])
                    total_chars += len(page_text)

                    page_area = float(page.width * page.height)
                    total_page_area += page_area

                    image_area_on_page = 0.0
                    for img in page.images:
                        image_area_on_page += float(img.get("width", 0) * img.get("height", 0))
                    total_image_area += image_area_on_page

                    if page_area > 0 and (image_area_on_page / page_area) >= self.figure_page_ratio_min:
                        figure_pages += 1

                    try:
                        extracted_tables = [t for t in (page.extract_tables() or []) if t]
                    except Exception:
                        extracted_tables = []
                    if extracted_tables:
                        table_pages += 1

                    if page.chars and any(ch.get("fontname") for ch in page.chars):
                        font_metadata_pages += 1

                    widgets = getattr(page, "annots", None) or []
                    if widgets:
                        widget_pages += 1

                    try:
                        words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
                    except Exception:
                        words = []

                    if len(words) >= 40:
                        midpoint = page.width / 2
                        left_count = sum(1 for word in words if float(word.get("x0", 0.0)) < midpoint * 0.95)
                        right_count = sum(1 for word in words if float(word.get("x0", 0.0)) >= midpoint * 1.05)
                        left_right_balance = min(left_count, right_count) / max(1, left_count + right_count)
                        approx_column_count = 1 + int(left_count > 0 and right_count > 0)
                        column_count_total += approx_column_count
                        if left_right_balance >= self.multi_column_ratio_min:
                            multi_column_pages += 1
                    else:
                        column_count_total += 1

                sampled_text = " ".join(all_sample_text)
                return {
                    "total_pages": total_pages,
                    "sampled_pages": pages_to_sample,
                    "avg_chars_per_page": total_chars / max(1, pages_to_sample),
                    "avg_char_density": total_chars / max(1.0, total_page_area),
                    "image_ratio": total_image_area / max(1.0, total_page_area),
                    "table_page_ratio": table_pages / max(1, pages_to_sample),
                    "multi_column_ratio": multi_column_pages / max(1, pages_to_sample),
                    "avg_column_count": column_count_total / max(1, pages_to_sample),
                    "figure_page_ratio": figure_pages / max(1, pages_to_sample),
                    "font_metadata_ratio": font_metadata_pages / max(1, pages_to_sample),
                    "widget_page_ratio": widget_pages / max(1, pages_to_sample),
                    "text_sample": " ".join(words_for_domain).lower(),
                    "amharic_char_ratio": self._calculate_amharic_ratio(sampled_text),
                }
        except Exception as exc:
            print(f"pdfplumber failed: {exc}")
            return {
                "total_pages": 0,
                "sampled_pages": 0,
                "avg_chars_per_page": 0,
                "avg_char_density": 0.0,
                "image_ratio": 1.0,
                "table_page_ratio": 0.0,
                "multi_column_ratio": 0.0,
                "avg_column_count": 1.0,
                "figure_page_ratio": 0.0,
                "font_metadata_ratio": 0.0,
                "widget_page_ratio": 0.0,
                "text_sample": "",
                "amharic_char_ratio": 0.0,
            }

    def _calculate_amharic_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        amharic_chars = sum(1 for char in text if "\u1200" <= char <= "\u137F")
        return amharic_chars / len(text)

    def _detect_origin(self, metrics: Dict[str, Any]) -> OriginType:
        avg_char_density = float(metrics.get("avg_char_density", 0.0))
        image_ratio = float(metrics.get("image_ratio", 0.0))
        avg_chars_per_page = float(metrics.get("avg_chars_per_page", 0.0))
        font_ratio = float(metrics.get("font_metadata_ratio", 0.0))
        widget_ratio = float(metrics.get("widget_page_ratio", 0.0))

        if widget_ratio >= self.form_fillable_widget_ratio_min and avg_char_density >= self.scanned_density_max:
            return OriginType.FORM_FILLABLE

        if avg_char_density <= self.scanned_density_max and image_ratio >= self.scanned_image_ratio_min:
            return OriginType.SCANNED_IMAGE
        if avg_char_density >= self.digital_density_min and image_ratio < self.scanned_image_ratio_min:
            return OriginType.NATIVE_DIGITAL
        if avg_char_density >= self.digital_density_min and avg_chars_per_page >= 150 and font_ratio > 0:
            return OriginType.NATIVE_DIGITAL
        if image_ratio > 0.20 and avg_char_density > self.scanned_density_max:
            return OriginType.MIXED
        return OriginType.NATIVE_DIGITAL if avg_chars_per_page > 80 else OriginType.MIXED

    def _detect_layout(self, metrics: Dict[str, Any]) -> LayoutComplexity:
        table_heavy = float(metrics.get("table_page_ratio", 0.0)) >= self.table_page_ratio_min
        avg_column_count = float(metrics.get("avg_column_count", 1.0))
        multi_column = (
            float(metrics.get("multi_column_ratio", 0.0)) >= self.multi_column_ratio_min
            or avg_column_count >= self.multi_column_count_min
        )
        figure_heavy = float(metrics.get("figure_page_ratio", 0.0)) >= self.figure_page_ratio_min

        signal_count = sum(1 for signal in [table_heavy, multi_column, figure_heavy] if signal)
        if signal_count >= 2:
            return LayoutComplexity.MIXED
        if table_heavy:
            return LayoutComplexity.TABLE_HEAVY
        if multi_column:
            return LayoutComplexity.MULTI_COLUMN
        if figure_heavy:
            return LayoutComplexity.FIGURE_HEAVY
        return LayoutComplexity.SINGLE_COLUMN

    def _detect_domain(self, metrics: Dict[str, Any]) -> DomainHint:
        return self.domain_classifier.classify(metrics.get("text_sample", ""))

    def _estimate_cost(self, origin: OriginType, layout: LayoutComplexity, is_amharic: bool = False) -> CostEstimate:
        if origin == OriginType.SCANNED_IMAGE or is_amharic:
            return CostEstimate.NEEDS_VISION_MODEL
        if layout in {LayoutComplexity.TABLE_HEAVY, LayoutComplexity.MULTI_COLUMN, LayoutComplexity.MIXED, LayoutComplexity.FIGURE_HEAVY}:
            return CostEstimate.NEEDS_LAYOUT_MODEL
        return CostEstimate.FAST_TEXT_SUFFICIENT

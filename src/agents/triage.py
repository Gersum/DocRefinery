import os
from typing import Any, Dict, Optional, Protocol

import pdfplumber

from src.config import domain_keyword_map, extraction_threshold
from src.models.profile import CostEstimate, DocumentProfile, DomainHint, LayoutComplexity, OriginType


class DomainClassifier(Protocol):
    def classify(self, text: str) -> DomainHint:
        ...


class KeywordDomainClassifier:
    """Simple, pluggable domain classifier strategy."""

    def __init__(self, rules_path: Optional[str] = None, keyword_map: Optional[Dict[str, list[str]]] = None):
        self.keyword_map = keyword_map or domain_keyword_map(rules_path=rules_path)

    def classify_with_label(self, text: str) -> tuple[DomainHint, str]:
        normalized = text.lower()
        for domain_key, keywords in self.keyword_map.items():
            if any(word in normalized for word in keywords):
                try:
                    return DomainHint(domain_key), domain_key
                except ValueError:
                    return DomainHint.CUSTOM, domain_key
        return DomainHint.GENERAL, DomainHint.GENERAL.value

    def classify(self, text: str) -> DomainHint:
        hint, _ = self.classify_with_label(text)
        return hint


class TriageAgent:
    """Analyzes a document to determine origin, layout, and routing strategy."""

    def __init__(
        self,
        sample_pages: int = 5,
        domain_classifier: Optional[DomainClassifier] = None,
        rules_path: Optional[str] = None,
    ):
        self.sample_pages = sample_pages
        self.domain_classifier = domain_classifier or KeywordDomainClassifier(rules_path=rules_path)
        self.scanned_density_max = float(extraction_threshold("origin_scanned_char_density_max", 0.0008, rules_path))
        self.digital_density_min = float(extraction_threshold("origin_digital_char_density_min", 0.0020, rules_path))
        self.scanned_image_ratio_min = float(extraction_threshold("origin_scanned_image_ratio_min", 0.50, rules_path))
        self.mixed_image_ratio_min = float(extraction_threshold("origin_mixed_image_ratio_min", 0.20, rules_path))
        self.digital_chars_floor = int(extraction_threshold("origin_digital_chars_floor", 80, rules_path))
        self.digital_chars_with_font_floor = int(extraction_threshold("origin_digital_chars_with_font_floor", 150, rules_path))
        self.form_fillable_widget_ratio_min = float(extraction_threshold("origin_form_fillable_widget_ratio_min", 0.10, rules_path))
        self.multi_column_ratio_min = float(extraction_threshold("layout_multi_column_ratio_min", 0.20, rules_path))
        self.multi_column_count_min = int(extraction_threshold("layout_multi_column_count_min", 2, rules_path))
        self.table_page_ratio_min = float(extraction_threshold("layout_table_page_ratio_min", 0.15, rules_path))
        self.figure_page_ratio_min = float(extraction_threshold("layout_figure_page_ratio_min", 0.20, rules_path))
        self.min_words_for_column_detection = int(extraction_threshold("layout_min_words_for_column_detection", 40, rules_path))
        self.column_left_split_factor = float(extraction_threshold("layout_column_left_split_factor", 0.95, rules_path))
        self.column_right_split_factor = float(extraction_threshold("layout_column_right_split_factor", 1.05, rules_path))
        self.language_amharic_ratio_threshold = float(extraction_threshold("language_amharic_ratio_threshold", 0.05, rules_path))
        self.language_confidence_floor = float(extraction_threshold("language_confidence_floor", 0.60, rules_path))
        self.language_confidence_base = float(extraction_threshold("language_confidence_base", 0.60, rules_path))

    def profile_document(self, file_path: str, doc_id: str) -> DocumentProfile:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        metrics = self._gather_metrics(file_path)
        origin = self._detect_origin(metrics)
        layout = self._detect_layout(metrics)
        domain, domain_label = self._detect_domain_with_label(metrics)

        amharic_ratio = metrics.get("amharic_char_ratio", 0.0)
        language = "am" if amharic_ratio > self.language_amharic_ratio_threshold else "en"
        language_confidence = min(1.0, max(self.language_confidence_floor, self.language_confidence_base + amharic_ratio))
        cost_est = self._estimate_cost(origin, layout, is_amharic=(language == "am"))

        return DocumentProfile(
            document_id=doc_id,
            origin_type=origin,
            layout_complexity=layout,
            language=language,
            language_confidence=language_confidence,
            domain_hint=domain,
            domain_label=domain_label,
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

                    if len(words) >= self.min_words_for_column_detection:
                        midpoint = page.width / 2
                        left_count = sum(
                            1 for word in words if float(word.get("x0", 0.0)) < midpoint * self.column_left_split_factor
                        )
                        right_count = sum(
                            1 for word in words if float(word.get("x0", 0.0)) >= midpoint * self.column_right_split_factor
                        )
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
        if avg_char_density >= self.digital_density_min and avg_chars_per_page >= self.digital_chars_with_font_floor and font_ratio > 0:
            return OriginType.NATIVE_DIGITAL
        if image_ratio > self.mixed_image_ratio_min and avg_char_density > self.scanned_density_max:
            return OriginType.MIXED
        return OriginType.NATIVE_DIGITAL if avg_chars_per_page > self.digital_chars_floor else OriginType.MIXED

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
        domain_hint, _ = self._detect_domain_with_label(metrics)
        return domain_hint

    def _detect_domain_with_label(self, metrics: Dict[str, Any]) -> tuple[DomainHint, str]:
        text = metrics.get("text_sample", "")
        classify_with_label = getattr(self.domain_classifier, "classify_with_label", None)
        if callable(classify_with_label):
            return classify_with_label(text)
        domain_hint = self.domain_classifier.classify(text)
        return domain_hint, domain_hint.value

    def _estimate_cost(self, origin: OriginType, layout: LayoutComplexity, is_amharic: bool = False) -> CostEstimate:
        if origin == OriginType.SCANNED_IMAGE or is_amharic:
            return CostEstimate.NEEDS_VISION_MODEL
        if layout in {LayoutComplexity.TABLE_HEAVY, LayoutComplexity.MULTI_COLUMN, LayoutComplexity.MIXED, LayoutComplexity.FIGURE_HEAVY}:
            return CostEstimate.NEEDS_LAYOUT_MODEL
        return CostEstimate.FAST_TEXT_SUFFICIENT

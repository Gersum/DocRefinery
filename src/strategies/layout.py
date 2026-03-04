from __future__ import annotations

import importlib.util
import time
from typing import Any, List, Optional

import pdfplumber

from src.config import extraction_threshold
from src.models.extraction import BoundingBox, ExtractedDocument, ExtractedPage, ExtractedTable, ExtractedText
from src.models.profile import DocumentProfile
from src.strategies.base import BaseExtractionStrategy
from src.strategies.docling_adapter import DoclingDocumentAdapter, PageSignals


class LayoutExtractor(BaseExtractionStrategy):
    """
    Strategy B: layout-aware extraction using Docling (docling_parse backend) and
    normalization through DoclingDocumentAdapter.
    """

    def __init__(self, rules_path: Optional[str] = None):
        self._last_confidence = 0.0
        self._last_cost = 0.0
        self._last_error: Optional[str] = None

        self.max_pages = int(extraction_threshold("layout_max_pages_per_document", 80, rules_path))
        self.min_chars = int(extraction_threshold("layout_min_chars_per_page", 120, rules_path))
        self.min_char_density = float(extraction_threshold("layout_min_char_density", 0.0007, rules_path))
        self.max_image_ratio = float(extraction_threshold("layout_max_image_ratio", 0.75, rules_path))
        self.base_cost = float(extraction_threshold("strategy_b_base_cost_usd", 0.005, rules_path))
        self.per_page_cost = float(extraction_threshold("strategy_b_cost_per_page_usd", 0.0015, rules_path))

        self.adapter = DoclingDocumentAdapter()
        self.docling_parser_cls = None
        if importlib.util.find_spec("docling_parse.pdf_parser") is not None:
            from docling_parse.pdf_parser import DoclingPdfParser

            self.docling_parser_cls = DoclingPdfParser

    def _extract_tables_with_bbox(self, pdf_page: Any, document_id: str, page_number: int) -> List[ExtractedTable]:
        tables: List[ExtractedTable] = []

        try:
            found_tables = pdf_page.find_tables() or []
        except Exception:
            found_tables = []

        if found_tables:
            for idx, table in enumerate(found_tables, start=1):
                rows = [row for row in (table.extract() or []) if row and any(cell for cell in row)]
                if len(rows) < 2:
                    continue
                headers = [str(cell or "").strip() for cell in rows[0]]
                data_rows = [[str(cell or "").strip() for cell in row] for row in rows[1:]]
                bbox = table.bbox if getattr(table, "bbox", None) else (0.0, 0.0, float(pdf_page.width), float(pdf_page.height))
                tables.append(
                    ExtractedTable(
                        table_id=f"{document_id}-p{page_number}-t{idx}",
                        page_num=page_number,
                        headers=headers,
                        data=data_rows,
                        bbox=BoundingBox(x0=float(bbox[0]), y0=float(bbox[1]), x1=float(bbox[2]), y1=float(bbox[3])),
                    )
                )
            return tables

        # Fallback when find_tables cannot determine explicit table bboxes.
        for idx, raw_table in enumerate(pdf_page.extract_tables() or [], start=1):
            rows = [row for row in raw_table if row and any(cell for cell in row)]
            if len(rows) < 2:
                continue
            headers = [str(cell or "").strip() for cell in rows[0]]
            data_rows = [[str(cell or "").strip() for cell in row] for row in rows[1:]]
            tables.append(
                ExtractedTable(
                    table_id=f"{document_id}-p{page_number}-t{idx}",
                    page_num=page_number,
                    headers=headers,
                    data=data_rows,
                    bbox=BoundingBox(x0=0.0, y0=0.0, x1=float(pdf_page.width), y1=float(pdf_page.height)),
                )
            )
        return tables

    def _calculate_page_confidence(self, signals: PageSignals) -> float:
        char_signal = min(1.0, signals.char_count / max(1, self.min_chars))
        char_density = signals.char_count / max(1.0, signals.page_area)
        density_signal = min(1.0, char_density / max(self.min_char_density, 1e-9))
        image_signal = 1.0 if signals.image_ratio <= self.max_image_ratio else max(0.0, 1.0 - ((signals.image_ratio - self.max_image_ratio) / 0.5))
        font_signal = 1.0 if signals.has_font_metadata else 0.25
        structure_signal = min(1.0, (signals.table_count + min(2, signals.figure_count)) / 3.0)

        confidence = (
            (0.30 * char_signal)
            + (0.25 * density_signal)
            + (0.20 * image_signal)
            + (0.15 * font_signal)
            + (0.10 * structure_signal)
        )

        # Strong hint of scan leakage: high image area with sparse characters.
        if signals.image_ratio > 0.80 and signals.char_count < int(self.min_chars * 0.5):
            confidence = min(confidence, 0.45)

        return max(0.0, min(1.0, confidence))

    def _fallback_pdfplumber_page(self, pdf_page: Any, profile: DocumentProfile, page_number: int, image_ratio: float) -> ExtractedPage:
        text = pdf_page.extract_text() or ""
        text_blocks = []
        if text.strip():
            text_blocks.append(
                ExtractedText(
                    text=text,
                    page_num=page_number,
                    bbox=BoundingBox(x0=0.0, y0=0.0, x1=float(pdf_page.width), y1=float(pdf_page.height)),
                )
            )

        tables = self._extract_tables_with_bbox(pdf_page, profile.document_id, page_number)
        has_font = bool(getattr(pdf_page, "chars", None)) and any(char.get("fontname") for char in pdf_page.chars)
        signals = PageSignals(
            char_count=len(text),
            page_area=float(pdf_page.width * pdf_page.height),
            image_ratio=image_ratio,
            has_font_metadata=has_font,
            table_count=len(tables),
            figure_count=len(pdf_page.images),
        )
        confidence = self._calculate_page_confidence(signals)

        return ExtractedPage(
            page_num=page_number,
            text_blocks=text_blocks,
            tables=tables,
            figures=[],
            confidence_score=confidence,
            strategy_used="Strategy B - LayoutExtractor (Fallback)",
        )

    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        start_time = time.time()
        pages: List[ExtractedPage] = []
        confidence_sum = 0.0
        processed_pages = 0
        self._last_error = None

        docling_doc = None
        docling_parser = None

        with pdfplumber.open(file_path) as pdf:
            max_pages = min(len(pdf.pages), self.max_pages)

            if self.docling_parser_cls is not None:
                try:
                    # Keep docling_parse noise down: recoverable font decode issues are common
                    # in enterprise PDFs and should not flood pipeline logs.
                    docling_parser = self.docling_parser_cls(loglevel="fatal")
                    docling_doc = docling_parser.load(file_path, lazy=True)
                except Exception as exc:
                    self._last_error = str(exc)
                    docling_doc = None

            for page_index in range(max_pages):
                page_number = page_index + 1
                processed_pages += 1
                pdf_page = pdf.pages[page_index]
                page_area = float(pdf_page.width * pdf_page.height) if pdf_page.width and pdf_page.height else 1.0
                image_area = sum(float(image.get("width", 0) * image.get("height", 0)) for image in pdf_page.images)
                image_ratio = image_area / max(1.0, page_area)

                if docling_doc is None:
                    extracted_page = self._fallback_pdfplumber_page(pdf_page, profile, page_number, image_ratio)
                    pages.append(extracted_page)
                    confidence_sum += extracted_page.confidence_score
                    continue

                try:
                    docling_page = docling_doc.get_page(page_number)
                    table_candidates = self._extract_tables_with_bbox(pdf_page, profile.document_id, page_number)
                    source_cells = docling_page.word_cells if getattr(docling_page, "word_cells", None) else docling_page.textline_cells
                    char_count = sum(len((getattr(cell, "text", "") or "").strip()) for cell in source_cells or [])
                    has_font_metadata = any(bool(getattr(cell, "font_name", None)) for cell in source_cells or [])
                    figure_count = len(getattr(docling_page, "bitmap_resources", []) or [])
                    signals = PageSignals(
                        char_count=char_count,
                        page_area=page_area,
                        image_ratio=image_ratio,
                        has_font_metadata=has_font_metadata,
                        table_count=len(table_candidates),
                        figure_count=figure_count,
                    )
                    confidence = self._calculate_page_confidence(signals)
                    extracted_page = self.adapter.adapt_docling_parse_page(
                        document_id=profile.document_id,
                        page_number=page_number,
                        docling_page=docling_page,
                        table_candidates=table_candidates,
                        strategy_used="Strategy B - LayoutExtractor",
                        image_ratio=image_ratio,
                        confidence=confidence,
                    )
                except Exception as exc:
                    self._last_error = str(exc)
                    extracted_page = self._fallback_pdfplumber_page(pdf_page, profile, page_number, image_ratio)

                pages.append(extracted_page)
                confidence_sum += extracted_page.confidence_score

        if docling_doc is not None:
            try:
                docling_doc.unload()
            except Exception:
                pass

        self._last_confidence = confidence_sum / max(1, processed_pages)
        self._last_cost = self.base_cost + (processed_pages * self.per_page_cost)

        return ExtractedDocument(
            document_id=profile.document_id,
            pages=pages,
            total_processing_time=time.time() - start_time,
            total_cost=self._last_cost,
        )

    def get_confidence(self) -> float:
        return self._last_confidence

    def get_cost_estimate(self) -> float:
        return self._last_cost

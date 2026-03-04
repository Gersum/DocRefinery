from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from src.models.extraction import BoundingBox, ExtractedFigure, ExtractedPage, ExtractedTable, ExtractedText


@dataclass
class PageSignals:
    """Signals used to compute page confidence for layout-aware extraction."""

    char_count: int
    page_area: float
    image_ratio: float
    has_font_metadata: bool
    table_count: int
    figure_count: int


class DoclingDocumentAdapter:
    """
    Normalizes Docling/Docling-parse output into the internal ExtractedPage schema.
    """

    @staticmethod
    def _rect_to_bbox(rect: Any) -> BoundingBox:
        x_values = [float(rect.r_x0), float(rect.r_x1), float(rect.r_x2), float(rect.r_x3)]
        y_values = [float(rect.r_y0), float(rect.r_y1), float(rect.r_y2), float(rect.r_y3)]
        return BoundingBox(
            x0=min(x_values),
            y0=min(y_values),
            x1=max(x_values),
            y1=max(y_values),
        )

    @staticmethod
    def _sort_cells_for_reading_order(cells: Iterable[Any]) -> List[Any]:
        # Docling coordinates are bottom-left origin. Top-most content has larger y.
        return sorted(
            list(cells),
            key=lambda cell: (-max(float(cell.rect.r_y0), float(cell.rect.r_y1), float(cell.rect.r_y2), float(cell.rect.r_y3)), float(cell.rect.r_x0)),
        )

    def adapt_docling_parse_page(
        self,
        document_id: str,
        page_number: int,
        docling_page: Any,
        table_candidates: List[ExtractedTable],
        strategy_used: str,
        image_ratio: float,
        confidence: float,
    ) -> ExtractedPage:
        text_blocks: List[ExtractedText] = []

        # Prefer word cells for tighter bboxes and better preservation of reading order.
        source_cells = docling_page.word_cells if getattr(docling_page, "word_cells", None) else docling_page.textline_cells
        for cell in self._sort_cells_for_reading_order(source_cells or []):
            text = (getattr(cell, "text", "") or "").strip()
            if not text:
                continue
            text_blocks.append(
                ExtractedText(
                    text=text,
                    page_num=page_number,
                    bbox=self._rect_to_bbox(cell.rect),
                    font_name=getattr(cell, "font_name", None),
                )
            )

        figures: List[ExtractedFigure] = []
        for idx, bitmap in enumerate(getattr(docling_page, "bitmap_resources", []) or [], start=1):
            figures.append(
                ExtractedFigure(
                    figure_id=f"{document_id}-p{page_number}-f{idx}",
                    page_num=page_number,
                    caption="",
                    bbox=self._rect_to_bbox(bitmap.rect),
                )
            )

        return ExtractedPage(
            page_num=page_number,
            text_blocks=text_blocks,
            tables=table_candidates,
            figures=figures,
            confidence_score=confidence,
            strategy_used=strategy_used,
        )

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class BoundingBox(BaseModel):
    """Represents a spatial location on a page (x0, y0, x1, y1)."""
    x0: float
    y0: float
    x1: float
    y1: float

class ExtractedText(BaseModel):
    """Raw text element extracted from the document."""
    text: str
    page_num: int
    bbox: Optional[BoundingBox] = None
    font_name: Optional[str] = None
    font_size: Optional[float] = None

class ExtractedTable(BaseModel):
    """A structured table extracted from the document."""
    table_id: str
    page_num: int
    data: List[List[str]]  # Raw grid data
    headers: Optional[List[str]] = None
    bbox: Optional[BoundingBox] = None

class ExtractedFigure(BaseModel):
    """A figure, chart, or image extracted from the document."""
    figure_id: str
    page_num: int
    caption: str = ""
    bbox: Optional[BoundingBox] = None

class ExtractedPage(BaseModel):
    """A single page normalized extracted output."""
    page_num: int
    text_blocks: List[ExtractedText] = []
    tables: List[ExtractedTable] = []
    figures: List[ExtractedFigure] = []
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    strategy_used: str = ""

class ExtractedDocument(BaseModel):
    """The normalized representation of the entire document post-extraction."""
    document_id: str
    pages: List[ExtractedPage] = []
    total_processing_time: float = 0.0
    total_cost: float = 0.0

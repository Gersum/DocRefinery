from typing import Any, List, Optional
from pydantic import BaseModel, Field, model_validator, field_validator

class BoundingBox(BaseModel):
    """Represents a spatial location on a page (x0, y0, x1, y1)."""
    x0: float = Field(..., ge=0.0)
    y0: float = Field(..., ge=0.0)
    x1: float = Field(..., ge=0.0)
    y1: float = Field(..., ge=0.0)

    @field_validator("x0", "y0", "x1", "y1", mode="before")
    @classmethod
    def clip_negative_floats(cls, v: Any) -> float:
        try:
            val = float(v)
            return 0.0 if -0.1 < val < 0 else val
        except (ValueError, TypeError):
            return v

    @model_validator(mode="after")
    def validate_bounds(self) -> "BoundingBox":
        if self.x1 <= self.x0:
            raise ValueError(f"x1 ({self.x1}) must be greater than x0 ({self.x0})")
        if self.y1 <= self.y0:
            raise ValueError(f"y1 ({self.y1}) must be greater than y0 ({self.y0})")
        return self

class ExtractedText(BaseModel):
    """Raw text element extracted from the document."""
    text: str = Field(..., min_length=1, description="Non-empty text content extracted")
    page_num: int = Field(..., ge=1, description="1-indexed numeric indicator of the page")
    bbox: Optional[BoundingBox] = None
    font_name: Optional[str] = None
    font_size: Optional[float] = Field(default=None, gt=0.0)

class ExtractedTable(BaseModel):
    """A structured table extracted from the document."""
    table_id: str = Field(..., min_length=1)
    page_num: int = Field(..., ge=1)
    data: List[List[str]] = Field(..., min_length=1, description="At least one row of data must be present")
    headers: Optional[List[str]] = None
    bbox: Optional[BoundingBox] = None

class ExtractedFigure(BaseModel):
    """A figure, chart, or image extracted from the document."""
    figure_id: str = Field(..., min_length=1)
    page_num: int = Field(..., ge=1)
    caption: str = ""
    bbox: Optional[BoundingBox] = None

class ExtractedPage(BaseModel):
    """A single page normalized extracted output."""
    page_num: int = Field(..., ge=1)
    text_blocks: List[ExtractedText] = Field(default_factory=list)
    tables: List[ExtractedTable] = Field(default_factory=list)
    figures: List[ExtractedFigure] = Field(default_factory=list)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    strategy_used: str = ""

class ExtractedDocument(BaseModel):
    """The normalized representation of the entire document post-extraction."""
    document_id: str = Field(..., min_length=1)
    pages: List[ExtractedPage] = Field(default_factory=list)
    total_processing_time: float = Field(default=0.0, ge=0.0)
    total_cost: float = Field(default=0.0, ge=0.0)

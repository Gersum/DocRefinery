from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.models.extraction import BoundingBox

class ChunkType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    LIST = "list"

class LDU(BaseModel):
    """Logical Document Unit - A semantically coherent chunk of extracted data."""
    ldu_id: str
    document_id: str
    content: str
    chunk_type: ChunkType
    page_refs: List[int]
    bounding_box: Optional[BoundingBox] = None
    parent_section: Optional[str] = None
    token_count: int = 0
    content_hash: str = Field(..., description="Unique MD5 or SHA256 of the content block")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="e.g. caption, layout context")

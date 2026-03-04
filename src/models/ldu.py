from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models.extraction import BoundingBox


class ChunkType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    LIST = "list"


class LDU(BaseModel):
    """Logical Document Unit - a semantically coherent chunk of extracted data."""

    ldu_id: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    chunk_type: ChunkType
    page_refs: List[int] = Field(..., min_length=1)
    bounding_box: Optional[BoundingBox] = None
    parent_section: Optional[str] = None
    parent_ldu_id: Optional[str] = Field(default=None, min_length=1)
    child_ldu_ids: List[str] = Field(default_factory=list)
    token_count: int = Field(default=0, ge=0)
    content_hash: str = Field(..., min_length=16, description="Unique MD5 or SHA256 of the content block")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="e.g. caption, layout context")

    @field_validator("page_refs")
    @classmethod
    def validate_page_refs(cls, value: List[int]) -> List[int]:
        if any(page < 1 for page in value):
            raise ValueError("page_refs must contain only positive 1-indexed page numbers")
        normalized = sorted(set(value))
        return normalized

    @model_validator(mode="after")
    def validate_chunk_relationships(self) -> "LDU":
        if self.parent_ldu_id == self.ldu_id:
            raise ValueError("parent_ldu_id cannot reference self")
        if self.ldu_id in self.child_ldu_ids:
            raise ValueError("child_ldu_ids cannot include self")
        if len(self.child_ldu_ids) != len(set(self.child_ldu_ids)):
            raise ValueError("child_ldu_ids must be unique")
        return self

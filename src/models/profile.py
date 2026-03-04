from enum import Enum
from pydantic import BaseModel, Field

class OriginType(str, Enum):
    NATIVE_DIGITAL = "native_digital"
    SCANNED_IMAGE = "scanned_image"
    MIXED = "mixed"
    FORM_FILLABLE = "form_fillable"

class LayoutComplexity(str, Enum):
    SINGLE_COLUMN = "single_column"
    MULTI_COLUMN = "multi_column"
    TABLE_HEAVY = "table_heavy"
    FIGURE_HEAVY = "figure_heavy"
    MIXED = "mixed"

class DomainHint(str, Enum):
    FINANCIAL = "financial"
    LEGAL = "legal"
    TECHNICAL = "technical"
    MEDICAL = "medical"
    CUSTOM = "custom"
    GENERAL = "general"

class CostEstimate(str, Enum):
    FAST_TEXT_SUFFICIENT = "fast_text_sufficient"
    NEEDS_LAYOUT_MODEL = "needs_layout_model"
    NEEDS_VISION_MODEL = "needs_vision_model"

class DocumentProfile(BaseModel):
    """Governs which extraction strategy the downstream stages will use."""
    document_id: str = Field(..., description="Unique identifier for the document")
    origin_type: OriginType
    layout_complexity: LayoutComplexity
    language: str = Field(default="en", description="Detected language code")
    language_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    domain_hint: DomainHint
    domain_label: str = Field(default="general", min_length=1, description="Resolved domain label from config keywords")
    estimated_extraction_cost: CostEstimate
    page_count: int = Field(default=0, description="Total number of pages in the document")

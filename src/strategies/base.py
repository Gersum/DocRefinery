from abc import ABC, abstractmethod
from src.models.extraction import ExtractedDocument
from src.models.profile import DocumentProfile

class BaseExtractionStrategy(ABC):
    """The shared interface for all extraction tiers (A, B, C)."""

    @abstractmethod
    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        """Runs the extraction and returns the normalized ExtractedDocument model."""
        pass

    @abstractmethod
    def get_confidence(self) -> float:
        """Returns the confidence score (0.0 to 1.0) of the last extraction run."""
        pass
    
    @abstractmethod
    def get_cost_estimate(self) -> float:
        """Returns the estimated cost (USD) of the last extraction run."""
        pass

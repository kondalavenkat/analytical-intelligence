from abc import ABC, abstractmethod
from ..models.standard_document import StandardDocument

class BaseExtractor(ABC):
    """
    Abstract base class for all extractors.
    Every extractor must implement the extract() method
    and return a StandardDocument.
    """

    @abstractmethod
    def extract(self, data: bytes, filename: str) -> StandardDocument:
        """
        Extract content from raw file bytes.
        
        Args:
            data:     Raw bytes of the uploaded file.
            filename: Original filename (used for extension + metadata).

        Returns:
            A partially populated StandardDocument.
            The orchestrator will complete the remaining fields.
        """
        raise NotImplementedError


class ExtractionService:
    """
    Routes extraction to the correct BaseExtractor implementation
    based on the ExtractionStrategy set by the PipelineRouter.
    """

    @staticmethod
    def extract(data: bytes, filename: str, strategy) -> StandardDocument:
        from ..models.standard_document import ExtractionStrategy
        from .structured_extractor import StructuredExtractor
        from .document_extractor import DocumentExtractor
        from .image_extractor import ImageExtractor

        extractor_map = {
            ExtractionStrategy.STRUCTURED: StructuredExtractor,
            ExtractionStrategy.DOCUMENT:   DocumentExtractor,
            ExtractionStrategy.IMAGE:      ImageExtractor,
        }

        extractor_cls = extractor_map.get(strategy, StructuredExtractor)
        extractor = extractor_cls()

        print(f"[ExtractionService] Using {extractor_cls.__name__} for '{filename}'")
        return extractor.extract(data, filename)

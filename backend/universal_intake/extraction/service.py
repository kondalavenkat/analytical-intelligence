from abc import ABC, abstractmethod
from pathlib import Path
from ..models.standard_document import StandardDocument


def get_extension(filename: str) -> str:
    """
    Shared helper: extracts the lowercase file extension without the dot.
    Examples:
        'report.PDF'  -> 'pdf'
        'data.csv'    -> 'csv'
        'README'      -> ''
    All extractors should use this instead of inline string splitting.
    """
    return Path(filename).suffix.lower().lstrip(".")

class BaseExtractor(ABC):
    """
    Abstract base class for all extractors.

    Contract:
        Every concrete extractor MUST inherit this class and implement extract()
        with exactly this signature:  extract(self, data: bytes, filename: str)

        Any deviation will raise TypeError at instantiation time (ABC enforcement),
        preventing silent interface mismatches from reaching production.

    Registration:
        Add new extractors to ExtractionService.extractor_map.
    """

    @abstractmethod
    def extract(self, data: bytes, filename: str) -> StandardDocument:
        """
        Extract content from raw file bytes.

        Args:
            data:     Raw bytes of the uploaded file.
            filename: Original filename (used for extension + metadata).
                      Use get_extension(filename) to derive the file extension.

        Returns:
            A fully or partially populated StandardDocument.
            ok=True  → extraction succeeded.
            ok=False → flag_reason contains the error message.
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

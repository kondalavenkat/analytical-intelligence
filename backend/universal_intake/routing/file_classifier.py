import io
from ..models.standard_document import FileType

class UnsupportedFileTypeError(Exception):
    pass

class FileClassifier:
    """
    Stage 1: Technical classification from extension + MIME type.
    Answers: What tool do I use to EXTRACT this file?
    Does NOT determine business meaning.
    """
    STRUCTURED = {"csv", "xlsx", "xls", "json", "tsv", "xml"}
    PDF        = {"pdf"}
    DOCUMENT   = {"docx", "doc", "pptx", "ppt", "txt"}
    IMAGE      = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}

    @classmethod
    def classify(cls, filename: str, data: bytes) -> FileType:
        ext = filename.lower().rsplit(".", 1)[-1]
        
        if ext in cls.STRUCTURED:
            return FileType.STRUCTURED
            
        if ext in cls.PDF:
            # Check if it has extractable text (digital) or needs OCR (scanned)
            if cls._has_text(data):
                return FileType.PDF_DIGITAL
            else:
                return FileType.PDF_SCANNED
                
        if ext in cls.DOCUMENT:
            return FileType.DOCUMENT
            
        if ext in cls.IMAGE:
            return FileType.IMAGE
            
        raise UnsupportedFileTypeError(f"Unsupported file extension: .{ext}")

    @staticmethod
    def _has_text(data: bytes) -> bool:
        """Check if PDF has extractable text (not scanned image)."""
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                # Check up to first 3 pages
                text = "".join(p.extract_text() or "" for p in pdf.pages[:3])
                return len(text.strip()) > 100
        except Exception as e:
            print(f"[FileClassifier] PDF text check failed: {e}")
            return False

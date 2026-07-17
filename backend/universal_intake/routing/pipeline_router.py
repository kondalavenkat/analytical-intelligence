from ..models.standard_document import FileType, ExtractionStrategy

class PipelineRouter:
    """
    Stage 2: Routes to the correct Extraction Strategy based on the FileType.
    This determines HOW the document will be read.
    """
    
    @classmethod
    def route(cls, file_type: FileType) -> ExtractionStrategy:
        if file_type == FileType.STRUCTURED:
            return ExtractionStrategy.STRUCTURED
            
        if file_type == FileType.PDF_DIGITAL:
            # Digital PDFs can be parsed directly (e.g., pdfplumber)
            return ExtractionStrategy.DOCUMENT
            
        if file_type in (FileType.IMAGE, FileType.PDF_SCANNED):
            # Scanned PDFs and images need OCR
            return ExtractionStrategy.IMAGE
            
        if file_type == FileType.DOCUMENT:
            # DOCX, PPTX, TXT
            return ExtractionStrategy.DOCUMENT
            
        # Default fallback
        return ExtractionStrategy.STRUCTURED

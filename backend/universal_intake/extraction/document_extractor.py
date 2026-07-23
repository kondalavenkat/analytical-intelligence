import io
import pandas as pd
from ..models.standard_document import StandardDocument, FileType, ExtractionStrategy
from .service import BaseExtractor, get_extension

class DocumentExtractor(BaseExtractor):
    """
    Extracts text and tables from unstructured documents (PDF, DOCX, PPTX, TXT).
    Replaced legacy libraries (pdfplumber, python-docx, PyMuPDF) with Unstructured.io.
    """
    def __init__(self):
        pass

    def extract(self, data: bytes, filename: str) -> StandardDocument:
        ext = get_extension(filename)
        doc = StandardDocument(
            file_type_ext=ext,
            technical_file_type=FileType.DOCUMENT,
            extraction_strategy=ExtractionStrategy.DOCUMENT,
            parser_used="unstructured"
        )
        
        try:
            if ext == "txt":
                doc.parser_used = "native_txt"
                all_text = [data.decode("utf-8", errors="replace")]
            elif ext == "pdf":
                doc.parser_used = "unstructured_pdf"
                from unstructured.partition.pdf import partition_pdf
                elements = partition_pdf(file=io.BytesIO(data))
                all_text = [str(el) for el in elements if str(el).strip()]
            elif ext in ("doc", "docx"):
                doc.parser_used = "unstructured_docx"
                from unstructured.partition.docx import partition_docx
                elements = partition_docx(file=io.BytesIO(data))
                all_text = [str(el) for el in elements if str(el).strip()]
            elif ext in ("ppt", "pptx"):
                doc.parser_used = "unstructured_pptx"
                from unstructured.partition.pptx import partition_pptx
                elements = partition_pptx(file=io.BytesIO(data))
                all_text = [str(el) for el in elements if str(el).strip()]
            else:
                doc.ok = False
                doc.flag_reason = f"Unsupported document extension: {ext}"
                return doc
                
            doc.raw_text = "\n".join(all_text)
            doc.page_count = 1
            
            # Convert to fallback DataFrame for unstructured text processing
            lines = doc.raw_text.split("\n")
            df = pd.DataFrame({"line_number": range(1, len(lines) + 1), "content": lines})
            
            doc.df = df
            doc.row_count = len(df)
            doc.col_count = 2
            doc.columns = ["line_number", "content"]
            doc.preview = df.head(5).fillna("").astype(str).values.tolist()
            doc.confidence = 0.90
            doc.ok = True
            
            return doc
            
        except Exception as e:
            doc.ok = False
            doc.flag_reason = f"Failed to extract document via Unstructured: {e}"
            return doc

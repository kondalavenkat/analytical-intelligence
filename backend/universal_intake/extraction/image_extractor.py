import io
import pandas as pd
import requests
import base64
from io import StringIO
from .service import BaseExtractor, get_extension
from ..models.standard_document import StandardDocument, FileType, ExtractionStrategy

MAX_IMAGE_PAGES = 100

class ImageExtractor(BaseExtractor):
    """
    Handles: PNG, JPG, JPEG, WEBP, BMP, TIFF and scanned PDFs.
    Pipeline:
      1. Uses Vision LLM (llava:13b via Ollama) to extract structured table data directly from images.
      2. No more Tesseract/OCR logic.
    """

    def extract(self, data: bytes, filename: str) -> StandardDocument:
        ext = get_extension(filename)
        doc = StandardDocument(
            file_type_ext=ext,
            technical_file_type=FileType.IMAGE,
            extraction_strategy=ExtractionStrategy.IMAGE,
            parser_used="ImageExtractor_Llava",
            ocr_used=False,
        )

        if not data:
            doc.ok = False
            doc.flag_reason = "File is empty (0 bytes)."
            return doc

        try:
            if ext == "pdf":
                try:
                    images_data = self._pdf_to_images(data)
                except Exception as pdf_err:
                    doc.ok = False
                    doc.flag_reason = f"Cannot extract images from PDF: {pdf_err}"
                    return doc
            else:
                images_data = [data]

            if not images_data:
                doc.ok = False
                doc.flag_reason = "No image data found."
                return doc

            all_csv = []
            
            # Use Vision LLM for each image page to extract structured tabular data
            for img_bytes in images_data:
                csv_data = self._run_vision_llm(img_bytes)
                if csv_data:
                    all_csv.append(csv_data)

            if not all_csv:
                doc.ok = False
                doc.flag_reason = "Vision LLM could not extract any structured data from the images."
                return doc

            # Combine CSV chunks and parse into DataFrame
            combined_csv = "\n".join(all_csv)
            doc.raw_text = combined_csv
            doc.page_count = len(images_data)
            doc.confidence = 0.95  # Vision LLM generally has high confidence for layouts

            try:
                # Try parsing as CSV to build the DataFrame
                df = pd.read_csv(StringIO(combined_csv), on_bad_lines='skip')
                if df.empty or len(df.columns) < 2:
                    # Fallback if CSV parsing fails or is just a single column of text
                    lines = [l.strip() for l in combined_csv.split("\n") if l.strip()]
                    df = pd.DataFrame({"line_number": range(1, len(lines) + 1), "content": lines})
            except Exception:
                # Fallback DataFrame
                lines = [l.strip() for l in combined_csv.split("\n") if l.strip()]
                df = pd.DataFrame({"line_number": range(1, len(lines) + 1), "content": lines})

            doc.df        = df
            doc.row_count = len(df)
            doc.col_count = len(df.columns)
            doc.columns   = df.columns.astype(str).tolist()
            doc.preview   = df.head(5).fillna("").astype(str).values.tolist()

            return doc

        except Exception as e:
            import traceback
            traceback.print_exc()
            doc.ok = False
            doc.flag_reason = f"Unexpected error during image extraction: {e}"
            return doc

    def _pdf_to_images(self, data: bytes) -> list:
        try:
            import fitz
        except ImportError:
            raise ImportError("PyMuPDF not installed. Run: pip install PyMuPDF")

        images = []
        try:
            pdf = fitz.open(stream=data, filetype="pdf")
            if len(pdf) == 0:
                 raise Exception("PDF contains no pages.")
                 
            pages_to_process = min(len(pdf), MAX_IMAGE_PAGES)
            for page_num in range(pages_to_process):
                page = pdf[page_num]
                mat  = fitz.Matrix(2, 2)
                pix  = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                images.append(img_bytes)
        finally:
             if 'pdf' in locals():
                 pdf.close()
        return images

    def _run_vision_llm(self, image_bytes: bytes) -> str:
        """
        Runs llava:13b to extract tables directly to CSV format.
        Replaces PyTesseract completely.
        """
        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            prompt = (
                "You are a data extraction specialist. Extract the data from this image into a clean CSV format. "
                "Include a header row. If there are no clear columns, just return the text line by line as CSV. "
                "Do NOT include any markdown formatting, explanation, or conversational text. ONLY output the raw CSV data."
            )
            
            resp = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llava:13b",
                    "prompt": prompt,
                    "images": [image_b64],
                    "stream": False,
                    "options": {"temperature": 0.0}
                },
                timeout=180
            )
            if resp.ok:
                return resp.json().get("response", "").strip()
            else:
                print(f"[ImageExtractor] Vision API failed: {resp.text}")
                return ""
        except Exception as e:
            print(f"[ImageExtractor] Vision extraction error: {e}")
            return ""

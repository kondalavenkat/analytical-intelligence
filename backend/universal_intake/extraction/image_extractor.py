import io
import pandas as pd
from .service import BaseExtractor
from ..models.standard_document import StandardDocument, FileType, ExtractionStrategy

MAX_IMAGE_PAGES = 100  # safety cap for scanned PDFs

class ImageExtractor(BaseExtractor):
    """
    Handles: PNG, JPG, JPEG, WEBP, BMP, TIFF and scanned PDFs.
    Pipeline:
      1. Preprocess image (grayscale, contrast boost via Pillow)
      2. Tesseract OCR → raw text + per-word confidence scores
      3. If confidence is adequate → LLM structuring into rows/columns
      4. Returns StandardDocument with extracted DataFrame
    """

    def extract(self, data: bytes, filename: str) -> StandardDocument:
        ext = filename.lower().rsplit(".", 1)[-1]
        doc = StandardDocument(
            file_type_ext=ext,
            technical_file_type=FileType.IMAGE,
            extraction_strategy=ExtractionStrategy.IMAGE,
            parser_used="ImageExtractor",
            ocr_used=True,
        )

        if not data:
            doc.ok = False
            doc.flag_reason = "File is empty (0 bytes)."
            return doc

        try:
            if ext == "pdf":
                # Scanned PDF → render pages as images first
                try:
                    images = self._render_pdf_pages(data)
                except Exception as pdf_err:
                    doc.ok = False
                    doc.flag_reason = f"Cannot extract images from PDF: {pdf_err}"
                    return doc
            else:
                try:
                    images = [self._load_image(data)]
                except Exception as img_err:
                    doc.ok = False
                    doc.flag_reason = f"Cannot open image (may be corrupt or unsupported format): {img_err}"
                    return doc

            if not images:
                doc.ok = False
                doc.flag_reason = "No image data found."
                return doc

            # Run OCR on each page/image
            all_text = []
            word_confidences = []
            tesseract_error = None

            for img in images:
                try:
                    preprocessed = self._preprocess(img)
                    text, conf_scores = self._run_ocr(preprocessed)
                    if text:
                        all_text.append(text)
                    word_confidences.extend(conf_scores)
                except Exception as ocr_err:
                    # Capture tesseract errors gracefully
                    tesseract_error = str(ocr_err)
                    print(f"[ImageExtractor] OCR error on page: {ocr_err}")
                    break # Stop processing further pages if OCR itself is failing

            if tesseract_error and not all_text:
                doc.ok = False
                if "tesseract is not installed" in tesseract_error.lower() or "not found" in tesseract_error.lower():
                    doc.flag_reason = (
                        "Tesseract OCR is not installed or not found on the system. "
                        "Cannot read text from images. Please install Tesseract."
                    )
                else:
                    doc.flag_reason = f"OCR processing failed: {tesseract_error}"
                return doc

            doc.raw_text   = "\n".join(all_text)
            doc.page_count = len(images)

            # Calculate average OCR confidence
            if word_confidences:
                avg_conf = sum(word_confidences) / len(word_confidences) / 100.0
            else:
                avg_conf = 0.0

            doc.confidence = round(avg_conf, 3)
            
            if not doc.raw_text.strip():
                 # Handle case where OCR completed but found zero text
                 doc.ok = False
                 doc.flag_reason = "OCR completed successfully but no readable text was found in the image."
                 return doc

            print(f"[ImageExtractor] OCR confidence: {doc.confidence:.1%}, "
                  f"text_len={len(doc.raw_text)}")

            # Build a basic DataFrame from the raw text (line-based)
            # The DocumentClassifier + LLM structuring will improve this later
            lines = [l.strip() for l in doc.raw_text.split("\n") if l.strip()]
            df    = pd.DataFrame({
                "line_number": range(1, len(lines) + 1),
                "content":     lines,
            })
            doc.df        = df
            doc.row_count = len(df)
            doc.col_count = 2
            doc.columns   = ["line_number", "content"]
            doc.preview   = df.head(5).fillna("").astype(str).values.tolist()

            return doc

        except Exception as e:
            import traceback
            traceback.print_exc()
            doc.ok = False
            doc.flag_reason = f"Unexpected error during image extraction: {e}"
            return doc

    # ── Image loading ─────────────────────────────────────────────────────────
    def _load_image(self, data: bytes):
        try:
            from PIL import Image, UnidentifiedImageError
        except ImportError:
            raise ImportError("Pillow not installed. Run: pip install Pillow")

        try:
            return Image.open(io.BytesIO(data)).copy() # return a copy to avoid closing issues
        except UnidentifiedImageError:
             raise Exception("File is not a valid image or is corrupted.")

    # ── Scanned PDF → images ─────────────────────────────────────────────────
    def _render_pdf_pages(self, data: bytes) -> list:
        """Convert each PDF page to a PIL Image for OCR."""
        try:
            import fitz  # PyMuPDF
            from PIL import Image
        except ImportError:
            raise ImportError("PyMuPDF not installed. Run: pip install PyMuPDF")

        pages = []
        try:
            pdf = fitz.open(stream=data, filetype="pdf")
            
            if len(pdf) == 0:
                 raise Exception("PDF contains no pages.")
                 
            pages_to_process = min(len(pdf), MAX_IMAGE_PAGES)
            for page_num in range(pages_to_process):
                page = pdf[page_num]
                mat  = fitz.Matrix(2, 2)   # 2x zoom for better OCR accuracy
                pix  = page.get_pixmap(matrix=mat)
                img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                pages.append(img)
        finally:
             if 'pdf' in locals():
                 pdf.close()
        return pages

    # ── Image preprocessing ───────────────────────────────────────────────────
    def _preprocess(self, image):
        """
        Enhance image for better OCR:
        - Handle RGBA safely
        - Convert to grayscale
        - Boost contrast
        """
        from PIL import ImageEnhance, ImageFilter
        
        try:
            # Handle RGBA (alpha channel) which can cause issues with some filters/conversions
            if image.mode == 'RGBA':
                # Create a white background and composite the image onto it
                background = image.__class__.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3]) # 3 is the alpha channel
                img = background
            else:
                img = image
                
            img = img.convert("L")                      # Grayscale
            img = ImageEnhance.Contrast(img).enhance(2.0) # Boost contrast
            img = img.filter(ImageFilter.SHARPEN)          # Sharpen
            return img
        except Exception as e:
            print(f"[ImageExtractor] Warning: Preprocessing failed, returning original image. Error: {e}")
            return image

    # ── Tesseract OCR ──────────────────────────────────────────────────────────
    def _run_ocr(self, image) -> tuple[str, list[float]]:
        """
        Run Tesseract OCR and return:
        - full extracted text
        - list of per-word confidence scores (0-100)
        """
        try:
            import pytesseract
            import sys
            import os
            
            # On Windows, try multiple common Tesseract installation paths
            if sys.platform.startswith('win'):
                common_paths = [
                    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                    os.path.join(os.environ.get('LOCALAPPDATA', ''), r'Programs\Tesseract-OCR\tesseract.exe')
                ]
                for t_path in common_paths:
                    if os.path.exists(t_path):
                        pytesseract.pytesseract.tesseract_cmd = t_path
                        # print(f"[ImageExtractor] Found Tesseract at: {t_path}")
                        break
        except ImportError:
            raise ImportError("pytesseract not installed. Run: pip install pytesseract")
            
        try:
            # Full text - using PSM 3 (auto) as default fallback instead of strict 6
            text = pytesseract.image_to_string(image, config="--psm 3")

            # Per-word confidence scores
            data = pytesseract.image_to_data(
                image, config="--psm 3", output_type=pytesseract.Output.DICT
            )
            confs = [
                float(c)
                for c in data.get("conf", [])
                if str(c).lstrip("-").isdigit() and float(c) >= 0
            ]

            return text.strip(), confs
            
        except pytesseract.TesseractNotFoundError:
             raise Exception("Tesseract is not installed or not in PATH.")
        except Exception as e:
             raise Exception(f"Tesseract execution failed: {e}")

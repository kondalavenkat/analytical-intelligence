import io
import re
import pandas as pd
from .service import BaseExtractor
from ..models.standard_document import StandardDocument, FileType, ExtractionStrategy

MAX_PARSE_ROWS = 10_000


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Universal tabular data cleaning.
    Extracted from the original app_core._clean_df() and enhanced.
    """
    # Strip whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]

    # Drop columns that are entirely null
    df = df.dropna(axis=1, how="all")

    # Drop columns with >95% nulls
    null_ratio = df.isna().mean()
    df = df[null_ratio[null_ratio < 0.95].index.tolist()]

    # Drop blob / essay columns (avg char length > 500)
    for col in df.select_dtypes(include=["object"]).columns:
        try:
            avg_len = df[col].dropna().astype(str).str.len().mean()
            if avg_len and avg_len > 500:
                df = df.drop(columns=[col])
        except Exception:
            pass

    # Normalize currency / percentage columns to numeric
    def _clean_numeric(s):
        if pd.isna(s) or s == "" or s is None:
            return None
        if isinstance(s, (int, float)):
            return s
        cleaned = re.sub(r"[₹$€£¥¢,\s%]", "", str(s))
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        return cleaned

    for col in df.select_dtypes(include=["object"]).columns:
        try:
            cleaned = df[col].apply(_clean_numeric)
            converted = pd.to_numeric(cleaned, errors="coerce")
            if converted.notna().sum() > len(df) * 0.5:
                df[col] = converted
        except Exception:
            pass

    # Normalize null-like strings ("N/A", "NA", "null", "none", "-")
    null_strings = {"n/a", "na", "null", "none", "-", "--", "nan"}
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].apply(
            lambda v: None if str(v).strip().lower() in null_strings else v
        )

    # Normalize boolean-like strings
    bool_map = {"yes": True, "no": False, "true": True, "false": False}
    for col in df.select_dtypes(include=["object"]).columns:
        unique_lower = set(str(v).strip().lower() for v in df[col].dropna().unique())
        if unique_lower.issubset(bool_map.keys()):
            df[col] = df[col].apply(
                lambda v: bool_map.get(str(v).strip().lower(), v) if pd.notna(v) else v
            )

    return df


class StructuredExtractor(BaseExtractor):
    """
    Handles: CSV, Excel (.xlsx/.xls), JSON, TSV
    Uses Pandas for extraction. No OCR, no LLM needed.
    Reuses and enhances the original parse_uploaded_file() logic.
    """

    def extract(self, data: bytes, filename: str) -> StandardDocument:
        ext = filename.lower().rsplit(".", 1)[-1]
        doc = StandardDocument(
            file_type_ext=ext,
            technical_file_type=FileType.STRUCTURED,
            extraction_strategy=ExtractionStrategy.STRUCTURED,
            parser_used="StructuredExtractor",
        )

        try:
            if ext == "csv":
                return self._parse_csv(data, doc)
            elif ext in ("xlsx", "xls"):
                return self._parse_excel(data, doc)
            elif ext == "json":
                return self._parse_json(data, doc)
            elif ext in ("tsv", "txt"):
                return self._parse_tsv(data, doc)
            elif ext == "xml":
                return self._parse_xml(data, doc)
            else:
                doc.ok = False
                doc.flag_reason = f"Unsupported structured type: .{ext}"
                return doc
        except Exception as e:
            import traceback
            traceback.print_exc()
            doc.ok = False
            doc.flag_reason = str(e)
            return doc

    # ── CSV ──────────────────────────────────────────────────────────────────
    def _parse_csv(self, data: bytes, doc: StandardDocument) -> StandardDocument:
        df = None
        for enc in ["utf-8", "latin-1", "cp1252", "utf-8-sig"]:
            try:
                df = pd.read_csv(
                    io.BytesIO(data), nrows=MAX_PARSE_ROWS,
                    encoding=enc, low_memory=False, on_bad_lines="skip",
                )
                print(f"[StructuredExtractor] Parsed CSV: {len(df)} rows, encoding={enc}")
                break
            except UnicodeDecodeError:
                continue

        if df is None:
            doc.ok = False
            doc.flag_reason = "Could not decode CSV. Try saving as UTF-8."
            return doc

        df = _clean_df(df)
        doc.df         = df
        doc.row_count  = len(df)
        doc.col_count  = len(df.columns)
        doc.columns    = df.columns.tolist()
        doc.preview    = df.head(5).fillna("").astype(str).values.tolist()
        doc.confidence = 0.97
        return doc

    # ── Excel ─────────────────────────────────────────────────────────────────
    def _parse_excel(self, data: bytes, doc: StandardDocument) -> StandardDocument:
        ext = doc.file_type_ext.lower()

        # Choose engine explicitly — pandas cannot auto-detect reliably
        # .xlsx / .xlsm  → openpyxl
        # .xls            → xlrd  (legacy format)
        primary_engine  = "openpyxl" if ext in ("xlsx", "xlsm") else "xlrd"
        fallback_engine = "xlrd"     if primary_engine == "openpyxl" else "openpyxl"

        xl = None
        errors = []
        for engine in (primary_engine, fallback_engine):
            try:
                xl = pd.ExcelFile(io.BytesIO(data), engine=engine)
                print(f"[StructuredExtractor] Opened Excel with engine={engine}")
                break
            except Exception as eng_err:
                errors.append(f"{engine}: {eng_err}")
                print(f"[StructuredExtractor] Engine '{engine}' failed: {eng_err}")

        if xl is None:
            # Check if this is a "Fake Excel" file (HTML masquerading as .xls)
            # This is very common with legacy web portal exports.
            is_html_fake = any("Expected BOF record; found b'<html" in str(e) for e in errors)
            if is_html_fake or data.lstrip().startswith(b"<html"):
                try:
                    # pd.read_html returns a list of DataFrames (one per table found)
                    dfs = pd.read_html(io.BytesIO(data))
                    if dfs:
                        df_s = _clean_df(dfs[0]) # Just take the first table
                        doc.df         = df_s
                        doc.row_count  = len(df_s)
                        doc.col_count  = len(df_s.columns)
                        doc.columns    = df_s.columns.tolist()
                        doc.preview    = df_s.head(5).fillna("").astype(str).values.tolist()
                        doc.confidence = 0.80
                        print(f"[StructuredExtractor] Recovered fake Excel (HTML) with {len(df_s)} rows")
                        return doc
                except Exception as html_err:
                    errors.append(f"html_fallback: {html_err}")

            doc.ok = False
            doc.flag_reason = f"Could not open Excel file. { ' | '.join(errors) }"
            return doc

        sheet_names = xl.sheet_names
        print(f"[StructuredExtractor] Excel sheets: {sheet_names}")

        sheets_data = {}
        for sname in sheet_names:
            try:
                df_s = xl.parse(sname, nrows=MAX_PARSE_ROWS)
                df_s = _clean_df(df_s)
                preview_s = df_s.head(5).fillna("").astype(str).values.tolist()
                sheets_data[sname] = {
                    "ok":        True,
                    "row_count": len(df_s),
                    "col_count": len(df_s.columns),
                    "columns":   df_s.columns.tolist(),
                    "preview":   preview_s,
                    "df":        df_s,
                }
                print(f"[StructuredExtractor] Sheet '{sname}': {len(df_s)} rows")
            except Exception as e:
                sheets_data[sname] = {"ok": False, "error": str(e)}

        first_valid = next(
            (s for s in sheet_names if sheets_data.get(s, {}).get("ok")), None
        )
        if not first_valid:
            doc.ok = False
            doc.flag_reason = "No readable sheets found in Excel file."
            return doc

        base           = sheets_data[first_valid]
        doc.df         = base["df"]
        doc.row_count  = base["row_count"]
        doc.col_count  = base["col_count"]
        doc.columns    = base["columns"]
        doc.preview    = base["preview"]
        doc.sheets     = sheets_data
        doc.sheet_name = first_valid
        doc.sheet_names = sheet_names
        doc.confidence  = 0.97
        return doc


    # ── JSON ──────────────────────────────────────────────────────────────────
    def _parse_json(self, data: bytes, doc: StandardDocument) -> StandardDocument:
        import json
        raw = json.loads(data.decode("utf-8"))
        df = pd.json_normalize(raw) if isinstance(raw, dict) else pd.DataFrame(raw)
        df = _clean_df(df)
        doc.df         = df
        doc.row_count  = len(df)
        doc.col_count  = len(df.columns)
        doc.columns    = df.columns.tolist()
        doc.preview    = df.head(5).fillna("").astype(str).values.tolist()
        doc.confidence  = 0.93
        return doc

    # ── TSV / plain text ──────────────────────────────────────────────────────
    def _parse_tsv(self, data: bytes, doc: StandardDocument) -> StandardDocument:
        sep = "\t" if doc.file_type_ext == "tsv" else None
        df = pd.read_csv(io.BytesIO(data), sep=sep, nrows=MAX_PARSE_ROWS,
                         engine="python", on_bad_lines="skip")
        df = _clean_df(df)
        doc.df         = df
        doc.row_count  = len(df)
        doc.col_count  = len(df.columns)
        doc.columns    = df.columns.tolist()
        doc.preview    = df.head(5).fillna("").astype(str).values.tolist()
        doc.confidence  = 0.90
        return doc

    # ── XML ───────────────────────────────────────────────────────────────────
    def _parse_xml(self, data: bytes, doc: StandardDocument) -> StandardDocument:
        try:
            df = pd.read_xml(io.BytesIO(data))
            df = _clean_df(df)
            doc.df         = df
            doc.row_count  = len(df)
            doc.col_count  = len(df.columns)
            doc.columns    = df.columns.tolist()
            doc.preview    = df.head(5).fillna("").astype(str).values.tolist()
            doc.confidence = 0.90
            return doc
        except Exception as e:
            doc.ok = False
            doc.flag_reason = f"Could not parse XML: {e}"
            return doc

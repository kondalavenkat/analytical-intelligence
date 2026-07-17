import re
import pandas as pd
from abc import ABC, abstractmethod
from ..models.standard_document import StandardDocument, DocumentSubtype


class BaseDomainNormalizer(ABC):
    """Abstract base class for all domain normalizers."""

    @abstractmethod
    def normalize(self, doc: StandardDocument) -> StandardDocument:
        raise NotImplementedError


# ── Generic Normalizer (default for CSV, Excel, JSON, TSV) ───────────────────

class GenericNormalizer(BaseDomainNormalizer):
    """
    General-purpose normalizer for structured files.
    Cleans column names and handles common formatting issues.
    """

    def normalize(self, doc: StandardDocument) -> StandardDocument:
        if doc.df is None:
            return doc

        df = doc.df.copy()

        # Sanitize column names (spaces → underscores, remove special chars)
        df.columns = [
            re.sub(r"[^a-zA-Z0-9_]", "_", str(c).strip()).strip("_")
            for c in df.columns
        ]
        # Collapse multiple underscores
        df.columns = [re.sub(r"_+", "_", c) for c in df.columns]

        doc.df      = df
        doc.columns = df.columns.tolist()
        return doc


# ── Invoice Normalizer ────────────────────────────────────────────────────────

class InvoiceNormalizer(BaseDomainNormalizer):
    """
    Domain normalizer for invoices and bills.
    Handles: GSTIN, invoice numbers, tax fields, vendor names, amounts.
    """

    GSTIN_PATTERN = re.compile(
        r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b"
    )
    INV_NUMBER_PATTERN = re.compile(r"\b(INV|BILL|TXN|#)?[-\s]?[0-9]{3,}\b", re.IGNORECASE)

    # Canonical column name aliases
    COLUMN_ALIASES = {
        "item_name":   ["item", "description", "product", "particulars", "goods"],
        "quantity":    ["qty", "quantity", "units"],
        "unit_price":  ["rate", "unit price", "price", "mrp", "unit_rate"],
        "total":       ["total", "amount", "total amount", "net amount", "value"],
        "tax_amount":  ["gst", "tax", "sgst", "cgst", "igst", "vat"],
        "vendor_name": ["vendor", "supplier", "from", "seller", "company"],
        "invoice_date":["date", "invoice date", "bill date"],
        "invoice_no":  ["invoice no", "invoice number", "inv no", "bill no"],
    }

    def normalize(self, doc: StandardDocument) -> StandardDocument:
        if doc.df is None:
            return doc

        df = doc.df.copy()

        # Normalize column names using aliases
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower().strip()
            for canonical, aliases in self.COLUMN_ALIASES.items():
                if any(alias in col_lower for alias in aliases):
                    col_map[col] = canonical
                    break

        if col_map:
            df = df.rename(columns=col_map)
            print(f"[InvoiceNormalizer] Renamed columns: {col_map}")

        # Extract GSTIN from raw text if available and store as metadata
        if doc.raw_text:
            gstins = self.GSTIN_PATTERN.findall(doc.raw_text)
            if gstins:
                print(f"[InvoiceNormalizer] Detected GSTINs: {gstins}")

        # Convert amount-like columns to numeric
        amount_cols = ["total", "unit_price", "tax_amount", "quantity"]
        for col in amount_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(r"[₹$,€£\s]", "", regex=True),
                    errors="coerce"
                )

        doc.df      = df
        doc.columns = df.columns.tolist()
        return doc


# ── Bank Statement Normalizer ─────────────────────────────────────────────────

class BankStatementNormalizer(BaseDomainNormalizer):
    """
    Domain normalizer for bank statements.
    Handles: debit, credit, balance, transaction date, UTR numbers.
    """

    COLUMN_ALIASES = {
        "date":        ["date", "txn date", "transaction date", "value date", "posting date"],
        "description": ["description", "narration", "particulars", "remarks", "details"],
        "debit":       ["debit", "dr", "withdrawal", "paid out"],
        "credit":      ["credit", "cr", "deposit", "paid in", "received"],
        "balance":     ["balance", "closing balance", "running balance", "available balance"],
        "reference":   ["utr", "ref", "reference", "chq no", "transaction id"],
    }

    def normalize(self, doc: StandardDocument) -> StandardDocument:
        if doc.df is None:
            return doc

        df = doc.df.copy()

        # Normalize column names
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower().strip()
            for canonical, aliases in self.COLUMN_ALIASES.items():
                if any(alias in col_lower for alias in aliases):
                    col_map[col] = canonical
                    break
        if col_map:
            df = df.rename(columns=col_map)
            print(f"[BankStatementNormalizer] Renamed columns: {col_map}")

        # Convert numeric columns
        for col in ["debit", "credit", "balance"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(r"[₹$,€£\s\(\)]", "", regex=True),
                    errors="coerce"
                )

        # Parse date column
        if "date" in df.columns:
            try:
                df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
            except Exception:
                pass

        doc.df      = df
        doc.columns = df.columns.tolist()
        return doc


# ── Salary Slip Normalizer ────────────────────────────────────────────────────

class SalarySlipNormalizer(BaseDomainNormalizer):
    """
    Domain normalizer for salary slips / payslips.
    Handles: gross, net, deductions, PF, TDS, employee/employer.
    """

    COLUMN_ALIASES = {
        "employee_name":  ["employee", "emp name", "name"],
        "employee_id":    ["emp id", "employee id", "staff id"],
        "employer":       ["employer", "company", "organization"],
        "month":          ["month", "pay period", "salary month"],
        "gross_salary":   ["gross", "gross salary", "gross pay", "ctc"],
        "basic_pay":      ["basic", "basic salary", "basic pay"],
        "hra":            ["hra", "house rent", "house rent allowance"],
        "pf_deduction":   ["pf", "provident fund", "epf"],
        "tds":            ["tds", "income tax", "tax deducted"],
        "net_salary":     ["net", "net salary", "net pay", "take home", "in hand"],
    }

    def normalize(self, doc: StandardDocument) -> StandardDocument:
        if doc.df is None:
            return doc

        df = doc.df.copy()

        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower().strip()
            for canonical, aliases in self.COLUMN_ALIASES.items():
                if any(alias in col_lower for alias in aliases):
                    col_map[col] = canonical
                    break
        if col_map:
            df = df.rename(columns=col_map)
            print(f"[SalarySlipNormalizer] Renamed columns: {col_map}")

        # Convert monetary columns to numeric
        money_cols = ["gross_salary", "basic_pay", "hra", "pf_deduction", "tds", "net_salary"]
        for col in money_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(r"[₹$,€£\s]", "", regex=True),
                    errors="coerce"
                )

        doc.df      = df
        doc.columns = df.columns.tolist()
        return doc


# ── Factory ───────────────────────────────────────────────────────────────────

class DomainNormalizerFactory:
    """Returns the correct normalizer for the given business document subtype."""

    _MAP = {
        DocumentSubtype.INVOICE:        InvoiceNormalizer,
        DocumentSubtype.BANK_STATEMENT: BankStatementNormalizer,
        DocumentSubtype.SALARY_SLIP:    SalarySlipNormalizer,
    }

    @classmethod
    def get(cls, subtype: DocumentSubtype) -> BaseDomainNormalizer:
        normalizer_cls = cls._MAP.get(subtype, GenericNormalizer)
        return normalizer_cls()

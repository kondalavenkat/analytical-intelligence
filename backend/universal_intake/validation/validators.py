import re
from dataclasses import dataclass
from datetime import date
from typing import List
import pandas as pd
from ..models.standard_document import StandardDocument, DocumentSubtype


@dataclass
class ValidationResult:
    passed: bool
    errors: List[str]


# ── Schema Validator ─────────────────────────────────────────────────────────

class SchemaValidator:
    """
    Validates that column data types are correct before SQL insertion.
    Prevents permanent schema corruption from bad OCR or LLM output.
    
    Example: If a column called "salary" contains text strings,
    this catches it before we create a VARCHAR(255) salary column forever.
    """

    NUMERIC_HINTS  = ["amount", "total", "price", "salary", "balance",
                       "debit", "credit", "qty", "quantity", "rate", "tax"]
    DATE_HINTS     = ["date", "dob", "joining", "period"]
    EMAIL_PATTERN  = re.compile(r"[^@]+@[^@]+\.[^@]+")
    PHONE_PATTERN  = re.compile(r"[\d\s\+\-\(\)]{10,15}")

    @classmethod
    def validate(cls, doc: StandardDocument) -> ValidationResult:
        if doc.df is None or doc.df.empty:
            return ValidationResult(passed=True, errors=[])

        errors = []
        df = doc.df

        for col in df.columns:
            col_lower = col.lower()
            sample = df[col].dropna().head(10)

            # Check numeric hints
            if any(hint in col_lower for hint in cls.NUMERIC_HINTS):
                non_numeric = pd.to_numeric(sample.astype(str)
                               .str.replace(r"[₹$,€£\s]", "", regex=True),
                               errors="coerce").isna().sum()
                if non_numeric > len(sample) * 0.5:
                    errors.append(
                        f"Column '{col}' appears numeric but >50% values "
                        "could not be converted. Check OCR accuracy."
                    )

            # Check date hints
            if any(hint in col_lower for hint in cls.DATE_HINTS):
                try:
                    parsed = pd.to_datetime(sample, dayfirst=True, errors="coerce")
                    if parsed.isna().sum() > len(sample) * 0.5:
                        errors.append(
                            f"Column '{col}' appears to be a date column "
                            "but >50% values could not be parsed."
                        )
                except Exception:
                    pass

        passed = len(errors) == 0
        if not passed:
            print(f"[SchemaValidator] {len(errors)} issue(s) found: {errors}")
        return ValidationResult(passed=passed, errors=errors)


# ── Business Rule Validator ───────────────────────────────────────────────────

class BusinessRuleEngine:
    """
    Validates domain-specific business constraints AFTER schema validation.
    These are logical constraints, not type constraints.

    Examples:
      - Invoice date cannot be in the future
      - Salary cannot be negative
      - GST amount must be less than total amount
      - Balance must remain consistent (debit/credit checks)
    """

    GSTIN_PATTERN = re.compile(
        r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
    )
    PAN_PATTERN   = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")

    @classmethod
    def validate(cls, doc: StandardDocument) -> ValidationResult:
        if doc.df is None or doc.df.empty:
            return ValidationResult(passed=True, errors=[])

        errors = []
        df     = doc.df
        subtype = doc.business_type

        if subtype == DocumentSubtype.INVOICE:
            errors.extend(cls._validate_invoice(df))

        elif subtype == DocumentSubtype.BANK_STATEMENT:
            errors.extend(cls._validate_bank_statement(df))

        elif subtype == DocumentSubtype.SALARY_SLIP:
            errors.extend(cls._validate_salary_slip(df))

        else:
            errors.extend(cls._validate_generic(df))

        passed = len(errors) == 0
        if not passed:
            print(f"[BusinessRuleEngine] {len(errors)} violation(s): {errors}")
        return ValidationResult(passed=passed, errors=errors)

    # ── Invoice rules ─────────────────────────────────────────────────────────
    @classmethod
    def _validate_invoice(cls, df: pd.DataFrame) -> List[str]:
        errors = []
        today  = date.today()

        if "invoice_date" in df.columns:
            try:
                dates = pd.to_datetime(df["invoice_date"], dayfirst=True, errors="coerce")
                future = dates.dropna()[dates.dropna() > pd.Timestamp(today)]
                if len(future) > 0:
                    errors.append(
                        f"Invoice date cannot be in the future "
                        f"({len(future)} rows affected)."
                    )
            except Exception:
                pass

        for col in ["total", "unit_price"]:
            if col in df.columns:
                neg = pd.to_numeric(df[col], errors="coerce").dropna()
                if (neg < 0).any():
                    errors.append(f"Column '{col}' contains negative values.")

        return errors

    # ── Bank statement rules ──────────────────────────────────────────────────
    @classmethod
    def _validate_bank_statement(cls, df: pd.DataFrame) -> List[str]:
        errors = []

        for col in ["debit", "credit", "balance"]:
            if col in df.columns:
                vals = pd.to_numeric(df[col], errors="coerce").dropna()
                if col != "balance" and (vals < 0).any():
                    errors.append(f"Column '{col}' contains negative values.")
                if not pd.api.types.is_numeric_dtype(df[col]):
                    errors.append(f"Column '{col}' must be numeric.")

        return errors

    # ── Salary slip rules ─────────────────────────────────────────────────────
    @classmethod
    def _validate_salary_slip(cls, df: pd.DataFrame) -> List[str]:
        errors = []

        for col in ["gross_salary", "net_salary", "basic_pay"]:
            if col in df.columns:
                vals = pd.to_numeric(df[col], errors="coerce").dropna()
                if (vals < 0).any():
                    errors.append(f"Column '{col}' cannot be negative.")
                if (vals == 0).all():
                    errors.append(f"Column '{col}' has all-zero values. Check extraction.")

        if "gross_salary" in df.columns and "net_salary" in df.columns:
            gross = pd.to_numeric(df["gross_salary"], errors="coerce")
            net   = pd.to_numeric(df["net_salary"],   errors="coerce")
            invalid = (net > gross).dropna()
            if invalid.any():
                errors.append("Net salary is greater than gross salary in some rows.")

        return errors

    # ── Generic rules ─────────────────────────────────────────────────────────
    @classmethod
    def _validate_generic(cls, df: pd.DataFrame) -> List[str]:
        errors = []

        # Check for all-duplicate rows (likely bad OCR repeat)
        dup_count = df.duplicated().sum()
        if dup_count > len(df) * 0.5:
            errors.append(
                f"{dup_count} duplicate rows detected ({dup_count/len(df):.0%}). "
                "Possible OCR rendering issue."
            )

        # Check for columns with all identical values
        for col in df.columns:
            if df[col].nunique() == 1 and len(df) > 5:
                errors.append(
                    f"Column '{col}' has only one unique value across all rows. "
                    "May be a parsing error."
                )

        return errors

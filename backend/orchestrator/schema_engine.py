"""
Schema Intelligence Engine — V2.3 Enterprise Intelligence Platform

Generates rich SchemaMetadata from a DataFrame.
This becomes the knowledge base that all downstream components use.
No LLM involved — entirely deterministic.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np


@dataclass
class ColumnProfile:
    """Full profile of a single column."""
    name: str
    dtype: str
    semantic_type: str          # numeric, categorical, datetime, boolean, unique_id
    null_count: int
    null_pct: float
    unique_count: int
    is_unique: bool             # True if all values are distinct (potential ID column)
    sample_values: List[Any]    # First 5 non-null values
    # Numeric only
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean_value: Optional[float] = None
    std_value: Optional[float] = None
    # Categorical only
    top_values: Optional[List[str]] = None


@dataclass
class SchemaMetadata:
    """Complete metadata knowledge base for a DataFrame."""
    columns: List[str]
    row_count: int
    column_count: int
    numeric_columns: List[str]
    categorical_columns: List[str]
    datetime_columns: List[str]
    boolean_columns: List[str]
    unique_id_columns: List[str]        # columns that appear to be IDs (all unique)
    nullable_columns: List[str]         # columns with any nulls
    duplicate_row_count: int
    column_profiles: Dict[str, ColumnProfile] = field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Produce a compact schema summary suitable for LLM prompts."""
        lines = [
            f"Rows: {self.row_count} | Columns: {self.column_count}",
            f"Numeric columns: {self.numeric_columns}",
            f"Categorical columns: {self.categorical_columns}",
        ]
        if self.datetime_columns:
            lines.append(f"Datetime columns: {self.datetime_columns}")
        if self.duplicate_row_count > 0:
            lines.append(f"Duplicate rows: {self.duplicate_row_count}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "columns": self.columns,
            "numeric_columns": self.numeric_columns,
            "categorical_columns": self.categorical_columns,
            "datetime_columns": self.datetime_columns,
            "boolean_columns": self.boolean_columns,
            "unique_id_columns": self.unique_id_columns,
            "nullable_columns": self.nullable_columns,
            "duplicate_row_count": self.duplicate_row_count,
            "row_count": self.row_count,
            "column_count": self.column_count,
        }


def generate_schema_metadata(df: pd.DataFrame) -> SchemaMetadata:
    """
    Analyse a DataFrame and return a complete SchemaMetadata object.
    Entirely deterministic. No LLM involved.
    """
    columns = list(df.columns)
    row_count = len(df)
    column_count = len(columns)

    numeric_columns: List[str] = []
    categorical_columns: List[str] = []
    datetime_columns: List[str] = []
    boolean_columns: List[str] = []
    unique_id_columns: List[str] = []
    nullable_columns: List[str] = []
    column_profiles: Dict[str, ColumnProfile] = {}

    for col in columns:
        series = df[col]
        null_count = int(series.isnull().sum())
        null_pct = round(null_count / row_count * 100, 2) if row_count > 0 else 0.0
        unique_count = int(series.nunique())
        is_unique = (unique_count == row_count)
        sample_values = series.dropna().head(5).tolist()

        if null_count > 0:
            nullable_columns.append(col)

        # Determine semantic type
        if pd.api.types.is_bool_dtype(series):
            semantic_type = "boolean"
            boolean_columns.append(col)
            profile = ColumnProfile(
                name=col, dtype=str(series.dtype), semantic_type=semantic_type,
                null_count=null_count, null_pct=null_pct,
                unique_count=unique_count, is_unique=is_unique, sample_values=sample_values,
            )

        elif pd.api.types.is_numeric_dtype(series):
            semantic_type = "unique_id" if is_unique and unique_count > 50 else "numeric"
            if semantic_type == "unique_id":
                unique_id_columns.append(col)
            else:
                numeric_columns.append(col)
            profile = ColumnProfile(
                name=col, dtype=str(series.dtype), semantic_type=semantic_type,
                null_count=null_count, null_pct=null_pct,
                unique_count=unique_count, is_unique=is_unique, sample_values=sample_values,
                min_value=float(series.min()) if not series.isnull().all() else None,
                max_value=float(series.max()) if not series.isnull().all() else None,
                mean_value=float(series.mean()) if not series.isnull().all() else None,
                std_value=float(series.std()) if not series.isnull().all() else None,
            )

        elif pd.api.types.is_datetime64_any_dtype(series):
            semantic_type = "datetime"
            datetime_columns.append(col)
            profile = ColumnProfile(
                name=col, dtype=str(series.dtype), semantic_type=semantic_type,
                null_count=null_count, null_pct=null_pct,
                unique_count=unique_count, is_unique=is_unique, sample_values=sample_values,
            )

        else:
            # Try parsing formatted numeric (currency, commas) first
            if series.dtype == 'object' or pd.api.types.is_string_dtype(series):
                clean_series = series.astype(str).str.replace(r'[$,]', '', regex=True).str.strip()
                numeric_parsed = pd.to_numeric(clean_series, errors='coerce')
                
                # If more than 80% of values can be parsed as numbers
                if numeric_parsed.notna().sum() / max(row_count, 1) > 0.8:
                    semantic_type = "unique_id" if is_unique and unique_count > 50 else "numeric"
                    if semantic_type == "unique_id":
                        unique_id_columns.append(col)
                    else:
                        numeric_columns.append(col)
                        
                    # Normalize the dataframe in-place for all downstream operations
                    df[col] = numeric_parsed
                        
                    profile = ColumnProfile(
                        name=col, dtype=str(numeric_parsed.dtype), semantic_type=semantic_type,
                        null_count=null_count, null_pct=null_pct,
                        unique_count=unique_count, is_unique=is_unique, sample_values=sample_values,
                        min_value=float(numeric_parsed.min()) if not numeric_parsed.isnull().all() else None,
                        max_value=float(numeric_parsed.max()) if not numeric_parsed.isnull().all() else None,
                        mean_value=float(numeric_parsed.mean()) if not numeric_parsed.isnull().all() else None,
                        std_value=float(numeric_parsed.std()) if not numeric_parsed.isnull().all() else None,
                    )
                    column_profiles[col] = profile
                    continue

            # Object/string — try datetime detection
            parsed = pd.to_datetime(series, errors="coerce")
            if parsed.notna().sum() / max(row_count, 1) > 0.8:
                semantic_type = "datetime"
                datetime_columns.append(col)
                df[col] = parsed
            elif is_unique and unique_count > 50:
                semantic_type = "unique_id"
                unique_id_columns.append(col)
            else:
                semantic_type = "categorical"
                categorical_columns.append(col)

            top_vals = series.value_counts().head(5).index.tolist() if semantic_type == "categorical" else None
            profile = ColumnProfile(
                name=col, dtype=str(series.dtype), semantic_type=semantic_type,
                null_count=null_count, null_pct=null_pct,
                unique_count=unique_count, is_unique=is_unique, sample_values=sample_values,
                top_values=[str(v) for v in top_vals] if top_vals else None,
            )

        column_profiles[col] = profile

    duplicate_row_count = int(df.duplicated().sum())

    print("\n[Schema Engine Debug] Dataframe types after normalization:")
    print(df.dtypes)
    print()

    return SchemaMetadata(
        columns=columns,
        row_count=row_count,
        column_count=column_count,
        numeric_columns=numeric_columns,
        categorical_columns=categorical_columns,
        datetime_columns=datetime_columns,
        boolean_columns=boolean_columns,
        unique_id_columns=unique_id_columns,
        nullable_columns=nullable_columns,
        duplicate_row_count=duplicate_row_count,
        column_profiles=column_profiles,
    )

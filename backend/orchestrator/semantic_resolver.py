"""
Semantic Schema Resolver — V2.3 Enterprise Intelligence Platform

Maps question terms to actual DataFrame column names using:
  1. Exact match
  2. Business Dictionary expansion
  3. RapidFuzz fuzzy matching

IMPORTANT: This module ONLY resolves terms → columns.
           It does NOT infer aggregation (that lives in analytics_engine.py).

Returns MULTIPLE CANDIDATES per term so the Confidence Engine
can choose between options rather than guessing blindly.
"""

from typing import Optional, List, Tuple
from orchestrator.business_dictionary import expand_term_variants
from orchestrator.schema_engine import SchemaMetadata

try:
    from rapidfuzz import fuzz
    _FUZZY_ENGINE = "rapidfuzz"
except ImportError:
    import difflib
    _FUZZY_ENGINE = "difflib"

# Minimum score threshold to include a candidate
_DEFAULT_THRESHOLD = 60.0
# How many candidates to return per resolution
_DEFAULT_TOP_N = 3


def _fuzzy_score(query: str, candidate: str) -> float:
    if _FUZZY_ENGINE == "rapidfuzz":
        return fuzz.token_set_ratio(query.lower(), candidate.lower())
    return difflib.SequenceMatcher(None, query.lower(), candidate.lower()).ratio() * 100


def _get_candidates(
    term: str,
    candidates: List[str],
    threshold: float = _DEFAULT_THRESHOLD,
    top_n: int = _DEFAULT_TOP_N,
) -> List[Tuple[str, float]]:
    """
    Return top-N matching columns for a given term, sorted by score desc.
    Each result is (column_name, score_0_to_100).

    Example:
        _get_candidates("Sales", ["Revenue", "Sales_Amount", "Quantity"])
        → [("Revenue", 98.0), ("Sales_Amount", 89.0), ("Quantity", 52.0)]
    """
    if not candidates or not term:
        return []

    term_lower = term.strip().lower()
    score_map: dict[str, float] = {}

    # Expand via business dictionary
    expanded_terms = expand_term_variants(term)

    for col in candidates:
        col_lower = col.strip().lower()

        # Exact match
        if col_lower == term_lower:
            score_map[col] = 100.0
            continue

        # Dictionary-expanded exact matches
        for exp in expanded_terms:
            if col_lower == exp:
                score_map[col] = max(score_map.get(col, 0.0), 98.0)
                break

        # Fuzzy across all expanded terms
        for exp in expanded_terms:
            s = _fuzzy_score(exp, col)
            if s > score_map.get(col, 0.0):
                score_map[col] = s

    results = [
        (col, round(score, 1))
        for col, score in score_map.items()
        if score >= threshold
    ]
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]


class SemanticSchemaResolver:
    """
    Resolves natural language column references to actual DataFrame columns.
    Returns multiple candidates for each resolution — the Confidence Engine decides.
    Entirely deterministic — no LLM.
    """

    def __init__(self, schema: SchemaMetadata):
        self.schema = schema

    def resolve_entity(self, term: str, top_n: int = _DEFAULT_TOP_N) -> List[Tuple[str, float]]:
        """
        Resolve entity term → categorical column candidates.
        Returns list of (column_name, score), sorted by score desc.
        """
        # Try categorical columns first
        results = _get_candidates(term, self.schema.categorical_columns, top_n=top_n)
        if results:
            return results
        # Fall back to all non-numeric columns
        non_numeric = [c for c in self.schema.columns if c not in self.schema.numeric_columns]
        return _get_candidates(term, non_numeric, top_n=top_n)

    def resolve_metric(self, term: str, top_n: int = _DEFAULT_TOP_N) -> List[Tuple[str, float]]:
        """
        Resolve metric term → numeric column candidates.
        Returns list of (column_name, score), sorted by score desc.
        """
        return _get_candidates(term, self.schema.numeric_columns, top_n=top_n)

    def resolve_filter_column(self, term: str, top_n: int = _DEFAULT_TOP_N) -> List[Tuple[str, float]]:
        """Resolve filter column → any schema column candidates."""
        return _get_candidates(term, self.schema.columns, top_n=top_n)

    def infer_best_metric(self) -> Optional[str]:
        """When no metric is specified, infer the most likely numeric column."""
        metric_priority = ["revenue", "sales", "amount", "profit", "cost", "price", "quantity", "salary"]
        for priority_term in metric_priority:
            results = _get_candidates(priority_term, self.schema.numeric_columns, threshold=55.0, top_n=1)
            if results:
                return results[0][0]
        return self.schema.numeric_columns[0] if self.schema.numeric_columns else None

    def infer_best_entity(self) -> Optional[str]:
        """When no entity is specified, infer the best categorical column (lowest cardinality)."""
        if not self.schema.categorical_columns:
            return None
        candidates = [
            (col, self.schema.column_profiles[col].unique_count)
            for col in self.schema.categorical_columns
            if col in self.schema.column_profiles
        ]
        if not candidates:
            return self.schema.categorical_columns[0]
        return min(candidates, key=lambda x: x[1])[0]

    def best_entity(self, term: str) -> Optional[Tuple[str, float]]:
        """Convenience: return only the single best entity match."""
        results = self.resolve_entity(term, top_n=1)
        return results[0] if results else None

    def best_metric(self, term: str) -> Optional[Tuple[str, float]]:
        """Convenience: return only the single best metric match."""
        results = self.resolve_metric(term, top_n=1)
        return results[0] if results else None

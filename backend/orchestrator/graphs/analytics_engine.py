"""
Analytics Capability Engine — V2.3 Enterprise Intelligence Platform

Defines the platform's analytical capabilities.

Key design rules:
  - Capabilities are FAMILIES, not single operations.
  - Aggregation inference lives HERE (not in the semantic resolver).
  - Schema Resolver only maps terms → columns. Nothing else.
  - Growing the platform = adding a new capability here. LangGraph never changes.
"""

from typing import Dict, Any, Optional, List


ANALYTICS_CAPABILITIES: Dict[str, Dict[str, Any]] = {

    "ranking": {
        "description": (
            "Rank or compare entities by a metric to find top or bottom performers. "
            "Examples: 'top products by revenue', 'highest earning regions', "
            "'which customer spent the most', 'best departments by salary'."
        ),
        "requires_entity": True,
        "requires_metric": True,
        "supported_aggregations": ["sum", "mean", "count", "max", "min"],
        "aggregation_to_operation": {
            "sum":   "groupby_sum",
            "mean":  "groupby_mean",
            "count": "groupby_count",
            "max":   "groupby_max",
            "min":   "groupby_min",
        },
        "default_aggregation": "sum",
        "default_sort": "desc",
        "default_limit": 5,
        "default_chart": "bar",
    },

    "aggregation": {
        "description": (
            "Compute grouped totals, averages, sums, or counts across categories. "
            "Examples: 'revenue by product', 'sales by region', "
            "'average salary by department', 'how much did each branch earn'."
        ),
        "requires_entity": True,
        "requires_metric": True,
        "supported_aggregations": ["sum", "mean", "count", "max", "min"],
        "aggregation_to_operation": {
            "sum":   "groupby_sum",
            "mean":  "groupby_mean",
            "count": "groupby_count",
            "max":   "groupby_max",
            "min":   "groupby_min",
        },
        "default_aggregation": "sum",
        "default_sort": "desc",
        "default_limit": 20,
        "default_chart": "bar",
    },

    "distribution": {
        "description": (
            "Show how values are spread or distributed across categories. "
            "Examples: 'revenue distribution', 'breakdown by region', "
            "'frequency of products', 'proportion of order types'."
        ),
        "requires_entity": True,
        "requires_metric": False,
        "supported_aggregations": ["count"],
        "aggregation_to_operation": {
            "count": "value_counts",
        },
        "default_aggregation": "count",
        "default_sort": "desc",
        "default_limit": 20,
        "default_chart": "pie",
    },

    "filtering": {
        "description": (
            "Filter or search rows based on a condition or criteria. "
            "Examples: 'show sales in North region', 'find orders above 1000', "
            "'products with revenue less than 500', 'show only Keyboard sales'."
        ),
        "requires_entity": True,
        "requires_metric": False,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "filter": "filter",
        },
        "default_aggregation": "filter",
        "default_sort": None,
        "default_limit": 50,
        "default_chart": None,
    },

    "statistics": {
        "description": (
            "Compute statistical descriptors: mean, median, std, min, max, variance. "
            "Examples: 'describe the data', 'statistical summary', 'show dataset profile'."
        ),
        "requires_entity": False,
        "requires_metric": False,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "describe": "describe",
        },
        "default_aggregation": "describe",
        "default_sort": None,
        "default_limit": None,
        "default_chart": None,
    },

    "data_quality": {
        "description": (
            "Identify data quality issues: nulls, missing values, or duplicates. "
            "Examples: 'are there missing values', 'find nulls', 'show duplicates', "
            "'data quality check', 'incomplete records'."
        ),
        "requires_entity": False,
        "requires_metric": False,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "null": "null_summary",
            "duplicate": "duplicate_summary",
        },
        "default_aggregation": "null",
        "default_sort": None,
        "default_limit": None,
        "default_chart": None,
    },

    "count": {
        "description": (
            "Count total number of records or rows in the dataset. "
            "Examples: 'how many records', 'total number of sales', 'how many rows'."
        ),
        "requires_entity": False,
        "requires_metric": False,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "count": "count",
        },
        "default_aggregation": "count",
        "default_sort": None,
        "default_limit": None,
        "default_chart": None,
    },

    "distinct": {
        "description": (
            "Find unique or distinct values in a specific column. "
            "Examples: 'what are the unique products', 'list distinct regions', "
            "'different categories available', 'what values exist in Product'."
        ),
        "requires_entity": True,
        "requires_metric": False,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "distinct": "distinct",
        },
        "default_aggregation": "distinct",
        "default_sort": None,
        "default_limit": 50,
        "default_chart": None,
    },

    "trend": {
        "description": (
            "Analyse change over time or across a time dimension. "
            "Examples: 'monthly revenue trend', 'sales over time', "
            "'weekly order volume', 'revenue by quarter'."
        ),
        "requires_entity": True,      # datetime column
        "requires_metric": True,
        "supported_aggregations": ["sum", "mean", "count"],
        "aggregation_to_operation": {
            "sum":   "groupby_sum",
            "mean":  "groupby_mean",
            "count": "groupby_count",
        },
        "default_aggregation": "sum",
        "default_sort": "asc",
        "default_limit": 50,
        "default_chart": "line",
    },

    "correlation": {
        "description": (
            "Find relationships or correlation between two numeric columns. "
            "Examples: 'is revenue related to quantity', 'correlation between price and sales'."
        ),
        "requires_entity": False,
        "requires_metric": True,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "correlation": "correlation",
        },
        "default_aggregation": "correlation",
        "default_sort": None,
        "default_limit": None,
        "default_chart": "scatter",
    },

    "variance": {
        "description": (
            "Measure variability, spread, or deviation within a metric. "
            "Examples: 'variance in revenue', 'how variable are the sales'."
        ),
        "requires_entity": False,
        "requires_metric": True,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "describe": "describe",
        },
        "default_aggregation": "describe",
        "default_sort": None,
        "default_limit": None,
        "default_chart": None,
    },

    "pareto": {
        "description": (
            "Identify the 80/20 rule — which few entities drive most of the metric. "
            "Examples: 'which products drive 80% of revenue', 'Pareto analysis of sales'."
        ),
        "requires_entity": True,
        "requires_metric": True,
        "supported_aggregations": ["sum"],
        "aggregation_to_operation": {
            "sum": "groupby_sum",
        },
        "default_aggregation": "sum",
        "default_sort": "desc",
        "default_limit": 20,
        "default_chart": "bar",
    },

    "direct_qa": {
        "description": (
            "Answer a general question about the dataset without calculation. "
            "Examples: 'what is this file about', 'explain the columns', "
            "'what does Revenue mean', 'tell me about this data'."
        ),
        "requires_entity": False,
        "requires_metric": False,
        "supported_aggregations": [],
        "aggregation_to_operation": {
            "direct_qa": "direct_qa",
        },
        "default_aggregation": "direct_qa",
        "default_sort": None,
        "default_limit": 10,
        "default_chart": None,
    },
}


# ─────────────────────────────────────────────────────────────────
# Accessors
# ─────────────────────────────────────────────────────────────────

def get_capability(name: str) -> Optional[Dict[str, Any]]:
    return ANALYTICS_CAPABILITIES.get(name)


def get_capability_names() -> List[str]:
    return list(ANALYTICS_CAPABILITIES.keys())


def resolve_operation(capability_name: str, aggregation: str) -> Optional[str]:
    """Map capability + aggregation → exact registry operation name."""
    cap = ANALYTICS_CAPABILITIES.get(capability_name)
    if not cap:
        return None
    return cap["aggregation_to_operation"].get(aggregation)


# ─────────────────────────────────────────────────────────────────
# Aggregation Inference (moved here from semantic_resolver)
#
# This is BUSINESS LOGIC, not schema resolution.
# Schema Resolver only maps: "Sales" → "Revenue column".
# Capability Engine decides: that revenue column needs a SUM.
# ─────────────────────────────────────────────────────────────────

def infer_aggregation(metric_term: Optional[str], capability: str) -> str:
    """
    Deterministically infer the aggregation type from the metric term and capability.
    No LLM. Checks metric wording first, falls back to capability default.

    Examples:
        infer_aggregation("average salary", "aggregation")   → "mean"
        infer_aggregation("count of orders", "ranking")      → "count"
        infer_aggregation("total revenue", "ranking")        → "sum"
        infer_aggregation("revenue", "ranking")              → "sum"  (capability default)
    """
    if metric_term:
        term_lower = metric_term.lower()
        if any(w in term_lower for w in ["average", "avg", "mean"]):
            return "mean"
        if any(w in term_lower for w in ["count", "number of", "how many", "frequency", "occurrences"]):
            return "count"
        if any(w in term_lower for w in ["max", "maximum", "highest value", "peak", "largest"]):
            return "max"
        if any(w in term_lower for w in ["min", "minimum", "lowest value", "smallest"]):
            return "min"

    # Fall back to the capability's default aggregation
    cap = ANALYTICS_CAPABILITIES.get(capability, {})
    return cap.get("default_aggregation", "sum")

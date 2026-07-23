"""
Analytics Ontology for Structured Data Intelligence Engine.

Defines the core analytical CAPABILITIES of the platform.
Each capability is a semantic concept, not a keyword rule.

The LLM classifies user questions into capabilities.
The Planner maps capability + entity + metric → specific registry operation.

This design means:
  - "top products by revenue" → ranking + groupby_sum
  - "top products by order count" → ranking + groupby_count
  - "average salary by department" → aggregation + groupby_mean

Same capability. Different operations. No code changes needed.
"""

from typing import Dict, Any, Optional, List

# ─────────────────────────────────────────────────────────────────
# ANALYTICS CAPABILITIES
#
# Each capability defines:
#   description:              Human-readable description sent to LLM for classification.
#   requires_entity:          Needs a group_by column (categorical).
#   requires_metric:          Needs a value column (numeric).
#   supported_aggregations:   Which math operations are valid.
#   aggregation_to_operation: Maps aggregation type → registry function.
#   default_sort:             Default result ordering.
#   default_limit:            Default row limit.
#   default_chart:            Default chart type sent to frontend.
# ─────────────────────────────────────────────────────────────────

ANALYTICS_CAPABILITIES: Dict[str, Dict[str, Any]] = {

    "ranking": {
        "description": (
            "Rank or compare entities by a metric to find top or bottom performers. "
            "Examples: 'top products by revenue', 'highest earning regions', "
            "'which customer spent the most', 'best departments by sales'."
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
            "Compute grouped totals, averages, sums, or counts. "
            "Examples: 'revenue by product', 'sales by region', "
            "'average order by customer', 'how much did each department earn'."
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
            "'frequency of products', 'proportion of sales categories'."
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
            "Examples: 'show sales in the North region', 'find orders above 1000', "
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
            "Compute statistical descriptors like mean, median, standard deviation, min/max. "
            "Examples: 'describe the data', 'statistical summary', 'what is the variance', "
            "'show dataset profile'."
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
            "Examples: 'how many records are there', 'total number of sales', "
            "'how many rows', 'record count'."
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


def get_capability(name: str) -> Optional[Dict[str, Any]]:
    """Return a capability definition by name."""
    return ANALYTICS_CAPABILITIES.get(name)


def get_capability_names() -> List[str]:
    """Return all supported capability names."""
    return list(ANALYTICS_CAPABILITIES.keys())


def get_capability_descriptions_for_prompt() -> str:
    """
    Produce a prompt-ready list of capabilities with descriptions.
    Used by the LLM Intent Extractor node.
    """
    lines = []
    for name, cap in ANALYTICS_CAPABILITIES.items():
        lines.append(f"- {name}: {cap['description']}")
    return "\n".join(lines)


def resolve_operation(capability_name: str, aggregation: str) -> Optional[str]:
    """
    Map a capability + aggregation → exact registry operation name.
    Returns None if the mapping doesn't exist.
    """
    cap = ANALYTICS_CAPABILITIES.get(capability_name)
    if not cap:
        return None
    return cap["aggregation_to_operation"].get(aggregation)

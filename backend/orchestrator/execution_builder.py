"""
Execution Plan Builder — V2.3 Enterprise Intelligence Platform

100% DETERMINISTIC. No LLM.

Receives:
  - capability name
  - resolved entity column (actual schema column name)
  - resolved metric column (actual schema column name)
  - aggregation type
  - options (sort, limit, filter_value)

Outputs:
  - Exact execution plan JSON ready for the Operation Registry
"""

from typing import Optional, Dict, Any
from orchestrator.graphs.analytics_engine import (
    ANALYTICS_CAPABILITIES,
    get_capability,
    resolve_operation,
    infer_aggregation,
)


def build_execution_plan(
    capability: str,
    entity_column: Optional[str],
    metric_column: Optional[str],
    aggregation: Optional[str],
    sort: Optional[str] = None,
    limit: Optional[int] = None,
    filter_value: Optional[str] = None,
    filter_column: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a deterministic execution plan from resolved inputs.
    No guessing. No LLM. No dynamic code generation.
    """
    cap = get_capability(capability)
    if not cap:
        return {"error": f"Unknown capability: '{capability}'"}

    # Fill defaults from the capability definition
    effective_aggregation = aggregation or cap.get("default_aggregation", "sum")
    effective_sort = sort or cap.get("default_sort")
    effective_limit = limit or cap.get("default_limit")
    chart = cap.get("default_chart")

    # Resolve registry operation
    operation = resolve_operation(capability, effective_aggregation)
    if not operation:
        # Last-resort fallback to default aggregation
        operation = resolve_operation(capability, cap.get("default_aggregation", ""))
    if not operation:
        return {"error": f"Cannot resolve operation for capability='{capability}' aggregation='{effective_aggregation}'"}

    plan: Dict[str, Any] = {
        "operation": operation,
        "capability": capability,
        "aggregation": effective_aggregation,
        "sort": effective_sort,
        "ascending": (effective_sort == "asc"),
        "limit": effective_limit,
        "chart": chart,
    }

    # Add column-specific fields
    if entity_column:
        plan["group_by"] = entity_column
        plan["column"] = entity_column      # alias used by filter/distinct/value_counts

    if metric_column:
        plan["value"] = metric_column

    if filter_value is not None:
        plan["filter_value"] = filter_value

    if filter_column:
        plan["column"] = filter_column

    return plan

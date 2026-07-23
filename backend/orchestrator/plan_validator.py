"""
Plan Validator — V2.3 Enterprise Intelligence Platform

Pre-execution deterministic validation.
Checks the execution plan BEFORE any Pandas code runs.

Returns (is_valid: bool, error_message: str | None)
"""

from typing import Tuple, Optional, List
from orchestrator.schema_engine import SchemaMetadata


def validate_plan(
    plan: dict,
    schema: SchemaMetadata,
    supported_operations: List[str],
) -> Tuple[bool, Optional[str]]:
    """
    Run all pre-execution checks on the execution plan.
    Returns (True, None) if valid.
    Returns (False, "error reason") if invalid.
    """
    checks: List[str] = []
    operation = plan.get("operation")
    group_by = plan.get("group_by")
    value = plan.get("value")
    column = plan.get("column")
    limit = plan.get("limit")

    # ── Check 1: operation exists in registry ──────────────────────
    if not operation:
        return False, "Plan has no operation specified."
    if operation not in supported_operations:
        return False, (
            f"Operation '{operation}' not found in registry. "
            f"Supported: {supported_operations}"
        )
    checks.append(f"✅ operation '{operation}' registered")

    # ── Check 2: group_by must be a single string, not a list ──────
    if group_by is not None:
        if isinstance(group_by, list):
            return False, (
                f"'group_by' must be a single column string, not a list: {group_by}. "
                f"Categorical columns available: {schema.categorical_columns}"
            )
        if group_by not in schema.columns:
            return False, (
                f"group_by column '{group_by}' not found in dataset. "
                f"Available columns: {schema.columns}"
            )
        checks.append(f"✅ group_by '{group_by}' exists in schema")

    # ── Check 3: value column must exist and be numeric ─────────────
    if value is not None:
        if value not in schema.columns:
            return False, (
                f"metric column '{value}' not found in dataset. "
                f"Available columns: {schema.columns}"
            )
        if value not in schema.numeric_columns:
            return False, (
                f"metric column '{value}' is not numeric. "
                f"Numeric columns: {schema.numeric_columns}"
            )
        checks.append(f"✅ value '{value}' is numeric")

    # ── Check 4: filter column must exist ───────────────────────────
    if column is not None and column not in schema.columns:
        return False, (
            f"filter/distinct column '{column}' not found in dataset. "
            f"Available columns: {schema.columns}"
        )
    if column:
        checks.append(f"✅ column '{column}' exists")

    # ── Check 5: limit is a positive int ────────────────────────────
    if limit is not None:
        if not isinstance(limit, int) or limit <= 0:
            plan["limit"] = 10  # auto-correct instead of failing
        checks.append(f"✅ limit={plan.get('limit')}")

    print(f"[Plan Validator] " + " | ".join(checks))
    return True, None

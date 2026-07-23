"""
Result Validator — V2.3 Enterprise Intelligence Platform

Post-execution deterministic validation.
Checks the execution result BEFORE handing it to the Narrator.

Returns (is_valid: bool, error_message: str | None)
"""

from typing import Tuple, Optional, Dict, Any
import pandas as pd


def validate_result(result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate the output from the Operation Registry.
    Returns (True, None) if valid.
    Returns (False, "reason") if the result should not be narrated.
    """
    checks: List[str] = []

    # ── Check 1: no execution error ────────────────────────────────
    if "error" in result:
        return False, f"Registry execution failed: {result['error']}"

    # ── Check 2: result_df exists ──────────────────────────────────
    res_df = result.get("result_df")
    if res_df is None:
        return False, "Registry returned no DataFrame."

    # ── Check 3: result not empty ──────────────────────────────────
    if isinstance(res_df, pd.DataFrame) and res_df.empty:
        return False, "Execution produced an empty result. No matching data found."
    checks.append(f"✅ {len(res_df)} rows returned")

    # ── Check 4: execution metadata present ───────────────────────
    meta = result.get("metadata")
    if not meta:
        return False, "Execution metadata missing from registry result."
    checks.append(f"✅ metadata present | op={meta.get('operation')} | rows={meta.get('rows_processed')}")

    print(f"[Result Validator] " + " | ".join(checks))
    return True, None


# Allow the import at top of file without NameError
from typing import List

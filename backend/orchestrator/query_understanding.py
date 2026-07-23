"""
Query Understanding Engine — V2.3 Enterprise Intelligence Platform

LLM's ONLY job: understand intent and extract CONCEPTS.
Not column names. Not aggregation functions. Not Pandas logic.

Extracted fields:
  - capability       : analytical operation family
  - entity_term      : grouping concept (user's words)
  - metric_term      : measurement concept (user's words)
  - filter_column_term / filter_value : for filtering questions
  - sort             : "asc" or "desc"
  - limit            : how many rows
  - time_context     : detected time references (month, year, etc.)
  - comparison       : True if comparing two groups/periods
  - period_a / period_b : comparison periods if applicable
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from orchestrator.schema_engine import SchemaMetadata
from orchestrator.graphs.analytics_engine import ANALYTICS_CAPABILITIES


@dataclass
class QueryMeaning:
    """Structured understanding of a user's analytics question."""
    capability: str
    entity_term: Optional[str]
    metric_term: Optional[str]
    filter_column_term: Optional[str]
    filter_value: Optional[str]
    sort: Optional[str]
    limit: Optional[int]
    confidence: float

    # Time and comparison context
    time_context: Optional[str] = None         # "monthly", "quarterly", "yearly", etc.
    comparison: bool = False                    # True if question compares two things
    period_a: Optional[str] = None             # e.g., "this month", "Q1 2024"
    period_b: Optional[str] = None             # e.g., "last month", "Q1 2023"

    raw_llm_output: Optional[str] = None


def _build_capability_list() -> str:
    lines = []
    for name, cap in ANALYTICS_CAPABILITIES.items():
        lines.append(f"- {name}: {cap['description']}")
    return "\n".join(lines)


def extract_query_meaning(
    question: str,
    schema: SchemaMetadata,
    pcfg: Dict[str, Any],
) -> QueryMeaning:
    """
    Use LLM to extract query meaning — concepts only, never column names or Pandas.
    """
    from app_core import get_ai_completion

    capability_list = _build_capability_list()

    system_prompt = f"""You are an Analytics Query Understanding Engine.

Your ONLY job is to understand WHAT the user wants to analyze — not HOW to do it.

Analytical Capabilities (choose exactly one):
{capability_list}

Schema Context:
{schema.to_prompt_context()}

Rules:
1. Return ONLY valid JSON. No markdown.
2. "capability" must be exactly one of the listed names.
3. "entity_term" is the grouping concept in the user's own words (e.g. "Product"). NOT the column name.
4. "metric_term" is the measurement concept (e.g. "Revenue", "average salary"). NOT the column name.
5. "filter_column_term" and "filter_value": only for filter questions.
6. "sort": "asc", "desc", or null.
7. "limit": positive integer or null.
8. "confidence": 0.0–1.0.
9. "time_context": if question mentions a time period, extract it (e.g. "monthly", "by quarter", "last year"). Otherwise null.
10. "comparison": true if question asks to compare two groups or periods. Otherwise false.
11. "period_a" / "period_b": if comparison=true, extract both periods (e.g. "this month", "last month"). Otherwise null.

Response format:
{{
  "capability": "ranking",
  "entity_term": "Product",
  "metric_term": "Revenue",
  "filter_column_term": null,
  "filter_value": null,
  "sort": "desc",
  "limit": 5,
  "confidence": 0.97,
  "time_context": null,
  "comparison": false,
  "period_a": null,
  "period_b": null
}}"""

    try:
        raw = get_ai_completion(
            system_prompt,
            f"Question: {question}",
            provider=pcfg.get("provider", "ollama"),
            temperature=0.0,
            **{k: v for k, v in pcfg.items() if k not in ("provider", "temperature")}
        )
        clean = raw.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].strip()
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            clean = match.group(0)

        parsed = json.loads(clean)
        valid_caps = list(ANALYTICS_CAPABILITIES.keys())
        capability = parsed.get("capability", "").lower()
        if capability not in valid_caps:
            capability = "direct_qa"

        return QueryMeaning(
            capability=capability,
            entity_term=parsed.get("entity_term"),
            metric_term=parsed.get("metric_term"),
            filter_column_term=parsed.get("filter_column_term"),
            filter_value=parsed.get("filter_value"),
            sort=parsed.get("sort"),
            limit=int(parsed["limit"]) if parsed.get("limit") else None,
            confidence=float(parsed.get("confidence", 0.5)),
            time_context=parsed.get("time_context"),
            comparison=bool(parsed.get("comparison", False)),
            period_a=parsed.get("period_a"),
            period_b=parsed.get("period_b"),
            raw_llm_output=raw,
        )

    except Exception as e:
        print(f"[Query Understanding] Parse failed: {e}")
        return QueryMeaning(
            capability="direct_qa",
            entity_term=None, metric_term=None,
            filter_column_term=None, filter_value=None,
            sort=None, limit=None, confidence=0.0,
        )

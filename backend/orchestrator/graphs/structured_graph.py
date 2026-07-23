"""
Structured Data Intelligence Engine — LangGraph V2.3

Final 9-Stage Pipeline:

  Stage 1: Schema Intelligence        → Rich SchemaMetadata from DataFrame
  Stage 2: Query Understanding        → LLM extracts CONCEPTS only (capability, entity_term, metric_term)
  Stage 3: Semantic Schema Resolver   → Maps concepts → actual schema columns (RapidFuzz, no LLM)
  Stage 4: Execution Plan Builder     → 100% deterministic JSON plan
  Stage 5: Plan Validator             → Pre-execution checks (column exists, numeric, valid op)
  Stage 6: Operation Registry         → Pandas deterministic execution
  Stage 7: Result Validator           → Post-execution checks (not empty, metadata present)
  Stage 8: Narration Engine           → LLM explains verified data. Cannot invent numbers.
  Stage 9: handle_error               → Graceful fallback

LLM is called in:   Stage 2 (concept extraction), Stage 8 (narration)
LLM is NOT called:  Stages 1, 3, 4, 5, 6, 7, 9
"""

import json
import time
from typing import Dict, Any, Literal

import pandas as pd
from langgraph.graph import StateGraph, START, END

from orchestrator.state import PlatformState
from orchestrator.schema_engine import generate_schema_metadata
from orchestrator.query_understanding import extract_query_meaning
from orchestrator.semantic_resolver import SemanticSchemaResolver
from orchestrator.execution_builder import build_execution_plan
from orchestrator.plan_validator import validate_plan
from orchestrator.result_validator import validate_result
from orchestrator.confidence_engine import ConfidenceScore
from orchestrator.graphs.analytics_engine import (
    get_capability,
    infer_aggregation,
    get_capability_names,
)


# ─────────────────────────────────────────────────────────────────
# STAGE 1: Schema Intelligence
# ─────────────────────────────────────────────────────────────────

def schema_intelligence(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print("\n" + "=" * 60)
    print("  Structured Analytics Trace  V2.3")
    print("=" * 60)
    print(f"[Schema Intelligence] Analysing DataFrame...")

    df = state.get("metadata", {}).get("df")
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return {"error": "No structured data found. Please upload a CSV, Excel, or JSON file."}

    schema = generate_schema_metadata(df)

    print(f"[Schema Intelligence] Columns: {schema.columns}")
    print(f"[Schema Intelligence] Numeric: {schema.numeric_columns}")
    print(f"[Schema Intelligence] Categorical: {schema.categorical_columns}")
    print(f"[Schema Intelligence] Datetime: {schema.datetime_columns}")
    print(f"[Schema Intelligence] Rows: {schema.row_count} | Duplicates: {schema.duplicate_row_count}")
    print(f"[Schema Intelligence] Done in {(time.time()-t0)*1000:.0f}ms")

    return {"metadata": {"schema": schema, "schema_dict": schema.to_dict()}}


# ─────────────────────────────────────────────────────────────────
# STAGE 2: Query Understanding Engine (LLM — concepts only)
# ─────────────────────────────────────────────────────────────────

def query_understanding(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Query Understanding] Extracting intent and concepts...")

    question = state.get("user_input", "")
    pcfg = state.get("metadata", {}).get("pcfg", {})
    schema = state.get("metadata", {}).get("schema")

    if not schema:
        return {"error": "Schema metadata not available for query understanding."}

    meaning = extract_query_meaning(question, schema, pcfg)

    print(f"[Query Understanding] Capability: {meaning.capability} | Confidence: {meaning.confidence:.2f}")
    print(f"[Query Understanding] Entity term: '{meaning.entity_term}' | Metric term: '{meaning.metric_term}'")
    print(f"[Query Understanding] Filter: col='{meaning.filter_column_term}' val='{meaning.filter_value}'")
    print(f"[Query Understanding] Sort: {meaning.sort} | Limit: {meaning.limit}")
    print(f"[Query Understanding] Done in {(time.time()-t0)*1000:.0f}ms")

    return {"metadata": {"query_meaning": meaning}}


# ─────────────────────────────────────────────────────────────────
# STAGE 3: Semantic Schema Resolver (no LLM — RapidFuzz + dict)
# ─────────────────────────────────────────────────────────────────

def semantic_schema_resolver(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Semantic Resolver] Matching concepts to schema columns...")

    schema = state.get("metadata", {}).get("schema")
    meaning = state.get("metadata", {}).get("query_meaning")

    if not schema or not meaning:
        return {"error": "Missing schema or query meaning for semantic resolution."}

    resolver = SemanticSchemaResolver(schema)
    cap = get_capability(meaning.capability) or {}

    entity_candidates = []
    metric_candidates = []
    filter_col = None

    # Resolve entity
    if meaning.entity_term:
        entity_candidates = resolver.resolve_entity(meaning.entity_term)
        if entity_candidates:
            print(f"[Semantic Resolver] entity '{meaning.entity_term}' candidates: {entity_candidates}")
        else:
            inferred = resolver.infer_best_entity()
            entity_candidates = [(inferred, 50.0)] if inferred else []
            print(f"[Semantic Resolver] inferred entity → {entity_candidates}")
    elif cap.get("requires_entity"):
        inferred = resolver.infer_best_entity()
        entity_candidates = [(inferred, 100.0)] if inferred else []
        print(f"[Semantic Resolver] no entity term; inferred → {entity_candidates}")

    # Resolve metric
    if meaning.metric_term:
        metric_candidates = resolver.resolve_metric(meaning.metric_term)
        if metric_candidates:
            print(f"[Semantic Resolver] metric '{meaning.metric_term}' candidates: {metric_candidates}")
        else:
            inferred = resolver.infer_best_metric()
            metric_candidates = [(inferred, 50.0)] if inferred else []
            print(f"[Semantic Resolver] inferred metric → {metric_candidates}")
    elif cap.get("requires_metric"):
        inferred = resolver.infer_best_metric()
        metric_candidates = [(inferred, 100.0)] if inferred else []
        print(f"[Semantic Resolver] no metric term; inferred → {metric_candidates}")

    # Resolve filter column
    if meaning.filter_column_term:
        match = resolver.resolve_filter_column(meaning.filter_column_term, top_n=1)
        if match:
            filter_col = match[0][0]
            print(f"[Semantic Resolver] filter column '{meaning.filter_column_term}' → '{filter_col}'")

    # Compute confidence score
    confidence = ConfidenceScore(
        intent_confidence=meaning.confidence,
        entity_candidates=entity_candidates,
        metric_candidates=metric_candidates,
        requires_entity=bool(cap.get("requires_entity")),
        requires_metric=bool(cap.get("requires_metric")),
    )
    print(f"[Semantic Resolver] Overall confidence: {confidence.overall:.2f} [{confidence.gate_decision}]")
    print(f"[Semantic Resolver] Done in {(time.time()-t0)*1000:.0f}ms")

    # Pick top candidate for execution (if we proceed)
    resolved_entity = entity_candidates[0][0] if entity_candidates else None
    resolved_metric = metric_candidates[0][0] if metric_candidates else None

    # Infer aggregation deterministically
    aggregation = infer_aggregation(meaning.metric_term, meaning.capability)
    print(f"[Semantic Resolver] aggregation inferred → '{aggregation}'")

    return {"metadata": {
        "resolved_entity": resolved_entity,
        "resolved_metric": resolved_metric,
        "resolved_filter_col": filter_col,
        "aggregation": aggregation,
        "confidence_obj": confidence,  # pass object to next node
        "confidence": confidence.to_dict(),
    }}


# ─────────────────────────────────────────────────────────────────
# STAGE 3b: Confidence Gate
# ─────────────────────────────────────────────────────────────────

def confidence_gate(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Confidence Gate] Evaluating execution confidence...")

    question = state.get("user_input", "")
    meta = state.get("metadata", {})
    confidence: ConfidenceScore = meta.get("confidence_obj")

    if not confidence:
        return {}

    decision = confidence.gate_decision
    print(f"[Confidence Gate] Decision: {decision.upper()} (score: {confidence.overall:.2f})")

    if decision == "ask_user":
        msg = confidence.build_clarification_message(question)
        return {"response": msg, "evidence": []}  # This will halt the pipeline because response is populated
    elif decision == "stop":
        msg = confidence.build_stop_message(question)
        return {"response": msg, "evidence": []}

    return {}


# ─────────────────────────────────────────────────────────────────
# STAGE 4: Execution Plan Builder — 100% DETERMINISTIC. No LLM.
# ─────────────────────────────────────────────────────────────────

def execution_plan_builder(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Execution Builder] Building deterministic plan...")

    meta = state.get("metadata", {})
    meaning = meta.get("query_meaning")
    if not meaning:
        return {"error": "Query meaning not available for plan building."}

    plan = build_execution_plan(
        capability=meaning.capability,
        entity_column=meta.get("resolved_entity"),
        metric_column=meta.get("resolved_metric"),
        aggregation=meta.get("aggregation"),
        sort=meaning.sort,
        limit=meaning.limit,
        filter_value=meaning.filter_value,
        filter_column=meta.get("resolved_filter_col"),
    )

    if "error" in plan:
        return {"error": plan["error"]}

    # Inject confidence into plan for registry metadata
    plan["confidence"] = meta.get("confidence", {})

    print(f"[Execution Builder] Plan: {json.dumps({k:v for k,v in plan.items() if v is not None}, indent=2)}")
    print(f"[Execution Builder] Done in {(time.time()-t0)*1000:.0f}ms")

    return {"metadata": {"execution_plan": plan}}


# ─────────────────────────────────────────────────────────────────
# STAGE 5: Plan Validator — Deterministic pre-execution checks
# ─────────────────────────────────────────────────────────────────

def plan_validator_node(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Plan Validator] Running pre-execution checks...")

    if state.get("error"):
        return {}

    from orchestrator.graphs.operations import operation_registry
    meta = state.get("metadata", {})
    plan = meta.get("execution_plan", {})
    schema = meta.get("schema")

    if not schema:
        return {"error": "Schema not available for plan validation."}

    is_valid, error_msg = validate_plan(
        plan=plan,
        schema=schema,
        supported_operations=operation_registry.get_supported_operations(),
    )

    if not is_valid:
        return {"error": f"Plan Validator: {error_msg}"}

    print(f"[Plan Validator] ✅ All checks passed in {(time.time()-t0)*1000:.0f}ms")
    return {}


# ─────────────────────────────────────────────────────────────────
# STAGE 6: Operation Registry — Pandas deterministic execution
# ─────────────────────────────────────────────────────────────────

def execute_operation(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Operation Registry] Executing...")

    from orchestrator.graphs.operations import operation_registry

    df = state.get("metadata", {}).get("df")
    plan = state.get("metadata", {}).get("execution_plan", {})

    result = operation_registry.execute(plan, df)

    if "error" in result:
        return {"error": result["error"]}

    res_df = result.get("result_df")
    rows = len(res_df) if isinstance(res_df, pd.DataFrame) else "?"
    print(f"[Operation Registry] Returned {rows} rows in {(time.time()-t0)*1000:.0f}ms")
    if isinstance(res_df, pd.DataFrame):
        print(f"[Operation Registry] Preview:\n{res_df.head()}")

    return {"metadata": {"execution_result": result}}


# ─────────────────────────────────────────────────────────────────
# STAGE 7: Result Validator — Post-execution checks
# ─────────────────────────────────────────────────────────────────

def result_validator_node(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Result Validator] Running post-execution checks...")

    if state.get("error"):
        return {}

    result = state.get("metadata", {}).get("execution_result", {})
    is_valid, error_msg = validate_result(result)

    if not is_valid:
        return {"error": f"Result Validator: {error_msg}"}

    print(f"[Result Validator] ✅ Passed in {(time.time()-t0)*1000:.0f}ms")
    return {}


# ─────────────────────────────────────────────────────────────────
# STAGE 8: Narration Engine — LLM explains ONLY verified data
# ─────────────────────────────────────────────────────────────────

def narration_engine(state: PlatformState) -> Dict[str, Any]:
    t0 = time.time()
    print(f"\n[Narration Engine] Sending verified data to LLM...")

    from app_core import get_ai_completion

    question = state.get("user_input", "")
    pcfg = state.get("metadata", {}).get("pcfg", {})
    plan = state.get("metadata", {}).get("execution_plan", {})
    meaning = state.get("metadata", {}).get("query_meaning")
    exec_res = state.get("metadata", {}).get("execution_result", {})
    confidence = state.get("metadata", {}).get("confidence", {})

    res_df = exec_res.get("result_df")
    if res_df is None:
        return {"response": "No data available to explain."}

    data_text = res_df.to_string(index=False)
    exec_meta = exec_res.get("metadata", {})

    system_prompt = (
        "You are a professional business analyst. "
        "The data table below was produced by a deterministic analytics engine — "
        "the numbers are mathematically exact and have been verified. "
        "Your ONLY job is to explain these results clearly and concisely in plain English. "
        "Do NOT perform any arithmetic. Do NOT invent or modify any numbers. "
        "Use rich markdown formatting with tables where appropriate."
    )
    capability = meaning.capability if meaning else plan.get("capability", "")
    user_prompt = (
        f"User Question: {question}\n"
        f"Capability: {capability}\n"
        f"Operation: {plan.get('operation')} | Group By: {plan.get('group_by')} | Metric: {plan.get('value')}\n"
        f"Rows Processed: {exec_meta.get('rows_processed', '?')}\n\n"
        f"Verified Data:\n{data_text}"
    )

    try:
        narration = get_ai_completion(
            system_prompt, user_prompt,
            provider=pcfg.get("provider", "ollama"),
            temperature=0.2,
            **{k: v for k, v in pcfg.items() if k not in ("provider", "temperature")}
        )
    except Exception as e:
        print(f"[Narration Engine] LLM failed: {e}")
        narration = "Here are the computed results:"

    chart_data = exec_res.get("chart_data")
    evidence_item = {
        "table": "Structured Analytics Engine V2.3",
        "row": exec_meta.get("rows_processed", 0),
        "sql": (
            f"Capability: {capability} | "
            f"Operation: {plan.get('operation')} | "
            f"Group By: {plan.get('group_by')} | "
            f"Metric: {plan.get('value')} | "
            f"Rows Processed: {exec_meta.get('rows_processed', '?')} | "
            f"Confidence: {confidence.get('overall', '?')}"
        )
    }

    metadata_updates = {"chart_data": chart_data} if chart_data else {}
    print(f"[Narration Engine] Done in {(time.time()-t0)*1000:.0f}ms")
    print("=" * 60 + "\n")

    return {"response": narration, "evidence": [evidence_item], "metadata": metadata_updates}


# ─────────────────────────────────────────────────────────────────
# STAGE 9: Error Handler
# ─────────────────────────────────────────────────────────────────

def handle_error(state: PlatformState) -> Dict[str, Any]:
    err = state.get("error", "Unknown error.")
    print(f"\n[Structured Graph] ❌ {err}")
    print("=" * 60 + "\n")
    return {
        "response": f"I wasn't able to complete this analysis.\n\n**Reason:** {err}",
        "evidence": [],
    }


# ─────────────────────────────────────────────────────────────────
# ROUTING
# ─────────────────────────────────────────────────────────────────

def _route(ok_target: str, err_target: str = "handle_error"):
    def router(state: PlatformState) -> str:
        return err_target if state.get("error") else ok_target
    return router


# ─────────────────────────────────────────────────────────────────
# BUILD THE GRAPH
# ─────────────────────────────────────────────────────────────────

structured_builder = StateGraph(PlatformState)

structured_builder.add_node("schema_intelligence",      schema_intelligence)
structured_builder.add_node("query_understanding",      query_understanding)
structured_builder.add_node("semantic_schema_resolver", semantic_schema_resolver)
structured_builder.add_node("confidence_gate",          confidence_gate)
structured_builder.add_node("execution_plan_builder",   execution_plan_builder)
structured_builder.add_node("plan_validator",           plan_validator_node)
structured_builder.add_node("execute_operation",        execute_operation)
structured_builder.add_node("result_validator",         result_validator_node)
structured_builder.add_node("narration_engine",         narration_engine)
structured_builder.add_node("handle_error",             handle_error)

def _route_gate(state: PlatformState) -> str:
    if state.get("error"):
        return "handle_error"
    if state.get("response"):
        return END # halt pipeline
    return "execution_plan_builder"

structured_builder.add_edge(START, "schema_intelligence")
structured_builder.add_conditional_edges("schema_intelligence",      _route("query_understanding"))
structured_builder.add_conditional_edges("query_understanding",      _route("semantic_schema_resolver"))
structured_builder.add_conditional_edges("semantic_schema_resolver", _route("confidence_gate"))
structured_builder.add_conditional_edges("confidence_gate",          _route_gate)
structured_builder.add_conditional_edges("execution_plan_builder",   _route("plan_validator"))
structured_builder.add_conditional_edges("plan_validator",           _route("execute_operation"))
structured_builder.add_conditional_edges("execute_operation",        _route("result_validator"))
structured_builder.add_conditional_edges("result_validator",         _route("narration_engine"))
structured_builder.add_edge("narration_engine", END)
structured_builder.add_edge("handle_error",     END)

structured_graph = structured_builder.compile()

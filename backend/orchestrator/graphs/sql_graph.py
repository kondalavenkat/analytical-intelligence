from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, START, END
from orchestrator.state import PlatformState

# Nodes for SQL Sub-graph
def fetch_schema(state: PlatformState) -> Dict[str, Any]:
    # Schema is loaded beforehand and injected into metadata
    print("[SQL Graph] Fetching Database Schema")
    return {}

def generate_sql(state: PlatformState) -> Dict[str, Any]:
    from app_core import generate_sql_with_ai
    print("[SQL Graph] Generating SQL via app_core.py")
    
    tables = state.get("metadata", {}).get("tables", [])
    question = state.get("user_input", "")
    pcfg = state.get("metadata", {}).get("pcfg", {})
    
    gen_sql, gen_raw_sql = generate_sql_with_ai(tables, question, pcfg)
    return {"metadata": {"sql_query": gen_sql or "", "raw_sql": gen_raw_sql or ""}}

def validate_sql(state: PlatformState) -> Dict[str, Any]:
    print("[SQL Graph] Validating SQL syntax")
    sql_query = state.get("metadata", {}).get("sql_query")
    if not sql_query:
        return {"error": "Could not generate SQL query."}
    return {}

def execute_sql(state: PlatformState) -> Dict[str, Any]:
    print("[SQL Graph] Executing SQL against DB")
    import pandas as pd
    from sqlalchemy import text
    
    sql_query = state.get("metadata", {}).get("sql_query", "")
    engine = state.get("metadata", {}).get("engine")
    
    if sql_query.strip().rstrip(";") == "DIRECT_QA_REQUIRED":
        return {"metadata": {"direct_qa": True}}

    try:
        df = pd.read_sql(text(sql_query.rstrip(";")), engine)
        return {"metadata": {"df": df}}
    except Exception as e:
        return {"error": str(e)}

def explain_results(state: PlatformState) -> Dict[str, Any]:
    print("[SQL Graph] Explaining results")
    from app_core import analyze_data_with_ai
    
    df = state.get("metadata", {}).get("df")
    question = state.get("user_input", "")
    pcfg = state.get("metadata", {}).get("pcfg", {})
    
    analysis = ""
    if df is not None and not df.empty:
        try:
            analysis = analyze_data_with_ai(df, question, pcfg)
        except Exception as e:
            print(f"[SQL Graph] Analysis warning: {e}")
            
    return {"response": analysis, "evidence": [{"table": "Database", "row": len(df) if df is not None else 0}]}

def handle_error(state: PlatformState) -> Dict[str, Any]:
    print(f"[SQL Graph] Retrying failed SQL. Error: {state.get('error')}")
    from app_core import retry_sql_with_correction
    
    sql_query = state.get("metadata", {}).get("sql_query", "")
    tables = state.get("metadata", {}).get("tables", [])
    question = state.get("user_input", "")
    pcfg = state.get("metadata", {}).get("pcfg", {})
    err_str = str(state.get("error", ""))
    
    try:
        fixed_sql, fixed_raw = retry_sql_with_correction(sql_query, [err_str], tables, question, pcfg)
        return {"metadata": {"sql_query": fixed_sql, "raw_sql": fixed_raw}, "error": None}
    except Exception as e:
        return {"error": f"Retry failed: {e}"}

def route_sql(state: PlatformState) -> Literal["execute_sql", "handle_error"]:
    if state.get("error"):
        return "handle_error"
    return "execute_sql"

# Build SQL Graph
sql_builder = StateGraph(PlatformState)
sql_builder.add_node("fetch_schema", fetch_schema)
sql_builder.add_node("generate_sql", generate_sql)
sql_builder.add_node("validate_sql", validate_sql)
sql_builder.add_node("execute_sql", execute_sql)
sql_builder.add_node("explain_results", explain_results)
sql_builder.add_node("handle_error", handle_error)

sql_builder.add_edge(START, "fetch_schema")
sql_builder.add_edge("fetch_schema", "generate_sql")
sql_builder.add_edge("generate_sql", "validate_sql")
sql_builder.add_conditional_edges("validate_sql", route_sql)
sql_builder.add_edge("handle_error", "generate_sql")  # Retry loop
sql_builder.add_edge("execute_sql", "explain_results")
sql_builder.add_edge("explain_results", END)

sql_graph = sql_builder.compile()

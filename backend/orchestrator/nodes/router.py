from typing import Literal
from orchestrator.state import PlatformState

def route_execution(state: PlatformState) -> Literal["sql_graph", "file_graph", "structured_graph", "hybrid_graph", "evidence"]:
    """
    Deterministic router. 
    Routes based on the execution context instead of wasting an LLM call.
    """
    # Check if there was a cache hit
    if state.get("metadata", {}).get("cache_hit") is True:
        return "evidence"
        
    mode = state.get("mode", "sql")
    print(f"[LangGraph] Execution Router: Routing to {mode}_graph")
    
    if mode == "sql":
        return "sql_graph"
    elif mode == "file":
        category = state.get("metadata", {}).get("category", "")
        if category == "structured":
            return "structured_graph"
        return "file_graph"
    elif mode == "hybrid":
        return "hybrid_graph"
        
    return "sql_graph" # fallback

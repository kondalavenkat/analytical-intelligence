from typing import TypedDict, Any, List, Optional, Dict, Annotated

def merge_dicts(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    c = a.copy() if a else {}
    if b:
        c.update(b)
    return c

class PlatformState(TypedDict):
    """
    The unified state for the Enterprise Intelligence Platform.
    Flows through the Master Graph, SQL Graph, and File Graph.
    """
    # Request Identity
    request_id: str
    workspace_id: str
    session_id: str
    
    # User Context
    user_input: str
    mode: str  # "sql", "file", "hybrid"
    file_type: Optional[str]
    
    # LLM Settings
    provider: str
    llm_profile: str  # e.g., "SQL_PROFILE", "SUMMARY_PROFILE"
    
    # Execution Context
    retrieved_context: List[Dict[str, Any]]
    
    # Output
    evidence: List[Dict[str, Any]]
    response: str
    metadata: Annotated[Dict[str, Any], merge_dicts]
    error: Optional[str]

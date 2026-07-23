from typing import Dict, Any
from orchestrator.state import PlatformState

def load_workspace(state: PlatformState) -> Dict[str, Any]:
    """
    Node: Workspace Manager
    Responsible for enriching the state with the workspace context,
    active semantic indexes, chat history, and metadata.
    """
    print(f"[LangGraph] Workspace Node: Loading context for session {state.get('session_id')}")
    
    # In the future, this node will query the DB for:
    # 1. Past chat history for this session_id
    # 2. Active document indexes for this workspace_id
    # 3. User metadata
    
    # For now, we just pass the state through
    return {"metadata": {"workspace_loaded": True}}

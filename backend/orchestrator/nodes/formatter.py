from typing import Dict, Any
from orchestrator.state import PlatformState

def format_response(state: PlatformState) -> Dict[str, Any]:
    """
    Node: Response Formatter
    Ensures that regardless of which sub-graph executed, the final payload
    returned to the frontend is perfectly identical in structure.
    """
    print(f"[LangGraph] Response Formatter: Formatting final payload.")
    
    return {
        "metadata": {
            "formatted": True,
            "final_payload": {
                "answer": state.get("response", ""),
                "evidence": state.get("evidence", []),
                "metadata": state.get("metadata", {}),
                "suggestions": state.get("metadata", {}).get("suggestions", []),
                "confidence": state.get("metadata", {}).get("confidence", 1.0)
            }
        }
    }

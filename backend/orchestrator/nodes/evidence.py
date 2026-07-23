from typing import Dict, Any
from orchestrator.state import PlatformState

def compile_evidence(state: PlatformState) -> Dict[str, Any]:
    """
    Node: Evidence Compiler
    Standardizes raw evidence from SQL, File, or Hybrid graphs into a single format
    (Source, Location, Confidence).
    """
    print(f"[LangGraph] Evidence Compiler: Standardizing citations.")
    
    raw_evidence = state.get("evidence", [])
    standardized = []
    
    for ev in raw_evidence:
        # If it's already standardized, keep it
        if "location" in ev and "confidence" in ev:
            standardized.append(ev)
            continue
            
        # Standardize SQL Evidence
        if "table" in ev:
            standardized.append({
                "source": ev.get("table", "Database"),
                "location": f"Row {ev.get('row', 'N/A')}",
                "confidence": 1.0,
                "raw": ev
            })
        
        # Standardize File Evidence (LlamaIndex source nodes)
        elif "node_id" in ev or "page" in ev:
            standardized.append({
                "source": ev.get("filename", "Document"),
                "location": f"Page {ev.get('page', 'N/A')}" if "page" in ev else f"Chunk {ev.get('chunk', 'N/A')}",
                "confidence": ev.get("score", 0.0),
                "raw": ev
            })
            
    return {"evidence": standardized}

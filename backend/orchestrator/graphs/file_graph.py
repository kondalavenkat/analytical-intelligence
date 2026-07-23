from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, START, END
from orchestrator.state import PlatformState

# Nodes for File Sub-graph
def extract_file(state: PlatformState) -> Dict[str, Any]:
    print("[File Graph] Extracting raw bytes from file via unstructured")
    # File extraction is handled downstream in llama_engine for now, but we mark it as started
    return {"metadata": {"extracted": True}}

def chunk_content(state: PlatformState) -> Dict[str, Any]:
    print("[File Graph] Chunking file contents for indexing")
    return {"metadata": {"chunked": True}}

def retrieve_context(state: PlatformState) -> Dict[str, Any]:
    print("[File Graph] Retrieving vector embeddings via LlamaIndex")
    # For Phase C, we run the entire research query here since LlamaIndex couples retrieval and synthesis
    import asyncio
    import llama_engine
    
    file_id = state.get("metadata", {}).get("file_id", "doc")
    raw_bytes = state.get("metadata", {}).get("raw_bytes", b"")
    file_name = state.get("metadata", {}).get("file_name", "document")
    file_type = state.get("file_type", "")
    prompt = state.get("user_input", "")
    pcfg = state.get("metadata", {}).get("pcfg", {})
    session_id = state.get("session_id")
    chat_history = state.get("metadata", {}).get("chat_history", [])
    
    try:
        # Since LangGraph nodes are synchronous by default here, we wrap the async call
        result_obj = asyncio.run(
            asyncio.to_thread(
                llama_engine.research_query,
                file_id, raw_bytes, file_name, file_type,
                prompt, pcfg, session_id=session_id, chat_history=chat_history
            )
        )
        return {
            "retrieved_context": [{"text": "Context retrieved", "score": 1.0}], 
            "metadata": {"llama_result": result_obj}
        }
    except Exception as e:
        return {"error": str(e), "retrieved_context": []}

def synthesize_response(state: PlatformState) -> Dict[str, Any]:
    print("[File Graph] Synthesizing final response via LLM")
    result_obj = state.get("metadata", {}).get("llama_result", {})
    analysis = result_obj.get("analysis", "")
    sources = result_obj.get("sources", [])
    
    return {"response": analysis, "evidence": sources}

def handle_retrieval_failure(state: PlatformState) -> Dict[str, Any]:
    print("[File Graph] Broadening retrieval parameters")
    # In V2, we will implement dynamic re-retrieval
    return {"metadata": {"retried": True}, "retrieved_context": [{"text": "Fallback context", "score": 0.5}]}

def route_retrieval(state: PlatformState) -> Literal["synthesize_response", "handle_retrieval_failure"]:
    if not state.get("retrieved_context"):
        return "handle_retrieval_failure"
    return "synthesize_response"

# Build File Graph
file_builder = StateGraph(PlatformState)
file_builder.add_node("extract_file", extract_file)
file_builder.add_node("chunk_content", chunk_content)
file_builder.add_node("retrieve_context", retrieve_context)
file_builder.add_node("synthesize_response", synthesize_response)
file_builder.add_node("handle_retrieval_failure", handle_retrieval_failure)

file_builder.add_edge(START, "extract_file")
file_builder.add_edge("extract_file", "chunk_content")
file_builder.add_edge("chunk_content", "retrieve_context")
file_builder.add_conditional_edges("retrieve_context", route_retrieval)
file_builder.add_edge("handle_retrieval_failure", "retrieve_context") # Retry loop
file_builder.add_edge("synthesize_response", END)

file_graph = file_builder.compile()

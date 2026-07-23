from typing import Literal
from langgraph.graph import StateGraph, START, END
from orchestrator.state import PlatformState

from orchestrator.nodes.workspace import load_workspace
from orchestrator.nodes.cache import check_cache, save_cache
from orchestrator.nodes.router import route_execution
from orchestrator.nodes.evidence import compile_evidence
from orchestrator.nodes.formatter import format_response

from orchestrator.graphs.sql_graph import sql_graph
from orchestrator.graphs.file_graph import file_graph
from orchestrator.graphs.structured_graph import structured_graph

def check_cache_hit(state: PlatformState) -> Literal["route_execution", "compile_evidence"]:
    if state.get("metadata", {}).get("cache_hit"):
        return "compile_evidence"
    return "route_execution"

# Build Master Graph
master_builder = StateGraph(PlatformState)

# Add Shared Nodes
master_builder.add_node("load_workspace", load_workspace)
master_builder.add_node("check_cache", check_cache)
master_builder.add_node("compile_evidence", compile_evidence)
master_builder.add_node("format_response", format_response)
master_builder.add_node("save_cache", save_cache)

# Add Sub-graphs as nodes
def run_sql_graph(state: PlatformState):
    return sql_graph.invoke(state)

def run_file_graph(state: PlatformState):
    return file_graph.invoke(state)
    
def run_structured_graph(state: PlatformState):
    return structured_graph.invoke(state)

master_builder.add_node("sql_graph", run_sql_graph)
master_builder.add_node("file_graph", run_file_graph)
master_builder.add_node("structured_graph", run_structured_graph)

# Edges
master_builder.add_edge(START, "load_workspace")
master_builder.add_edge("load_workspace", "check_cache")

# Cache and Execution routing
def route_from_cache(state: PlatformState) -> Literal["compile_evidence", "sql_graph", "file_graph", "structured_graph"]:
    if state.get("metadata", {}).get("cache_hit"):
        return "compile_evidence"
    
    # If cache miss, delegate to mode router
    return route_execution(state)

master_builder.add_conditional_edges("check_cache", route_from_cache)

# Post-execution paths
master_builder.add_edge("sql_graph", "compile_evidence")
master_builder.add_edge("file_graph", "compile_evidence")
master_builder.add_edge("structured_graph", "compile_evidence")

master_builder.add_edge("compile_evidence", "format_response")
master_builder.add_edge("format_response", "save_cache")
master_builder.add_edge("save_cache", END)

master_orchestrator = master_builder.compile()

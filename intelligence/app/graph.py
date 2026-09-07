"""LangGraph wiring. Sequential: classify -> extract -> ground -> compare -> generate -> file."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    classify_node,
    compare_node,
    extract_node,
    file_outputs_node,
    generate_node,
    ground_node,
)
from .state import PipelineState


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("classify", classify_node)
    g.add_node("extract", extract_node)
    g.add_node("ground", ground_node)
    g.add_node("compare", compare_node)
    g.add_node("generate", generate_node)
    g.add_node("file_outputs", file_outputs_node)

    g.add_edge(START, "classify")
    g.add_edge("classify", "extract")
    g.add_edge("extract", "ground")
    g.add_edge("ground", "compare")
    g.add_edge("compare", "generate")
    g.add_edge("generate", "file_outputs")
    g.add_edge("file_outputs", END)

    return g.compile()

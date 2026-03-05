"""MainGraph：单图多入口编排。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes.capability_nodes import (
    aggregate_node,
    batch_collect_node,
    collect_urls_node,
    dispatch_node,
    execute_single_or_multi,
    field_extract_node,
    generate_config_node,
    plan_node,
    run_pipeline_node,
)
from .nodes.entry_nodes import (
    chat_clarify,
    chat_route_execution,
    normalize_pipeline_params,
    route_entry,
)
from .nodes.shared_nodes import build_artifact_index, build_summary, finalize_result
from .state import GraphState


def resolve_entry_route(state: dict[str, Any]) -> str:
    """根据 entry_mode 返回下一节点名。"""
    mapping = {
        "chat_pipeline": "chat_clarify",
        "pipeline_run": "normalize_pipeline_params",
        "collect_urls": "collect_urls_node",
        "generate_config": "generate_config_node",
        "batch_collect": "batch_collect_node",
        "field_extract": "field_extract_node",
        "multi_pipeline": "plan_node",
    }
    mode = str(state.get("entry_mode") or "")
    if mode not in mapping:
        return "finalize_result"
    return mapping[mode]


def resolve_node_outcome(state: dict[str, Any]) -> str:
    """根据 node_status 选择继续或收敛。"""
    if str(state.get("node_status") or "") == "ok":
        return "ok"
    return "error"


def build_main_graph():
    """构建并编译主图。"""
    graph = StateGraph(GraphState)

    graph.add_node("route_entry", route_entry)
    graph.add_node("chat_clarify", chat_clarify)
    graph.add_node("chat_route_execution", chat_route_execution)
    graph.add_node("execute_single_or_multi", execute_single_or_multi)
    graph.add_node("normalize_pipeline_params", normalize_pipeline_params)
    graph.add_node("run_pipeline_node", run_pipeline_node)
    graph.add_node("collect_urls_node", collect_urls_node)
    graph.add_node("generate_config_node", generate_config_node)
    graph.add_node("batch_collect_node", batch_collect_node)
    graph.add_node("field_extract_node", field_extract_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("dispatch_node", dispatch_node)
    graph.add_node("aggregate_node", aggregate_node)
    graph.add_node("build_artifact_index", build_artifact_index)
    graph.add_node("build_summary", build_summary)
    graph.add_node("finalize_result", finalize_result)

    graph.set_entry_point("route_entry")
    graph.add_conditional_edges(
        "route_entry",
        resolve_entry_route,
        {
            "chat_clarify": "chat_clarify",
            "normalize_pipeline_params": "normalize_pipeline_params",
            "collect_urls_node": "collect_urls_node",
            "generate_config_node": "generate_config_node",
            "batch_collect_node": "batch_collect_node",
            "field_extract_node": "field_extract_node",
            "plan_node": "plan_node",
            "finalize_result": "finalize_result",
        },
    )

    graph.add_conditional_edges(
        "chat_clarify",
        resolve_node_outcome,
        {"ok": "chat_route_execution", "error": "build_artifact_index"},
    )
    graph.add_conditional_edges(
        "chat_route_execution",
        resolve_node_outcome,
        {"ok": "execute_single_or_multi", "error": "build_artifact_index"},
    )
    graph.add_edge("execute_single_or_multi", "build_artifact_index")

    graph.add_conditional_edges(
        "normalize_pipeline_params",
        resolve_node_outcome,
        {"ok": "run_pipeline_node", "error": "build_artifact_index"},
    )
    graph.add_edge("run_pipeline_node", "build_artifact_index")

    graph.add_edge("collect_urls_node", "build_artifact_index")
    graph.add_edge("generate_config_node", "build_artifact_index")
    graph.add_edge("batch_collect_node", "build_artifact_index")
    graph.add_edge("field_extract_node", "build_artifact_index")

    graph.add_conditional_edges(
        "plan_node",
        resolve_node_outcome,
        {"ok": "dispatch_node", "error": "build_artifact_index"},
    )
    graph.add_conditional_edges(
        "dispatch_node",
        resolve_node_outcome,
        {"ok": "aggregate_node", "error": "build_artifact_index"},
    )
    graph.add_edge("aggregate_node", "build_artifact_index")

    graph.add_edge("build_artifact_index", "build_summary")
    graph.add_edge("build_summary", "finalize_result")
    graph.add_edge("finalize_result", END)
    return graph.compile()

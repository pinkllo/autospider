"""
MainGraph：单图多入口编排。
该模块负责构建整个自适应爬虫的主状态图（Main Graph），管理不同模式（如聊天、单页抓取、多页抓取等）下的状态流转与节点执行。
基于 LangGraph 实现，通过单一的入口根据 entry_mode 进行路由分发。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes.capability_nodes import (
    aggregate_node,
    batch_collect_node,
    collect_urls_node,
    field_extract_node,
    generate_config_node,
    plan_node,
    run_pipeline_node,
)
from .nodes.entry_nodes import (
    chat_clarify,
    chat_collect_user_input,
    chat_history_match,
    chat_review_task,
    chat_route_execution,
    normalize_pipeline_params,
    route_entry,
)
from .nodes.shared_nodes import build_artifact_index, build_summary, finalize_result
from .state import GraphState
from .subgraphs import build_multi_dispatch_subgraph



def resolve_entry_route(state: dict[str, Any]) -> str:
    """
    根据 entry_mode（入口模式）返回下一个需要执行的节点名。
    此函数作为条件边的路由逻辑，决定状态图的初始分支走向。
    """
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
    """根据 node_status 选择图后续流向。"""
    if str(state.get("node_status") or "") == "ok":
        return "ok"
    return "error"



def resolve_chat_clarify_route(state: dict[str, Any]) -> str:
    """根据 chat 澄清阶段结果选择后续节点。"""
    if str(state.get("node_status") or "") != "ok":
        return "error"

    flow_state = str(state.get("chat_flow_state") or "")
    if flow_state == "needs_input":
        return "chat_collect_user_input"
    if flow_state == "ready":
        return "chat_history_match"
    return "error"



def resolve_chat_review_route(state: dict[str, Any]) -> str:
    """根据 chat review 阶段结果选择后续节点。"""
    if str(state.get("node_status") or "") != "ok":
        return "error"

    review_state = str(state.get("chat_review_state") or "")
    if review_state == "approved":
        return "chat_route_execution"
    if review_state == "reclarify":
        return "chat_clarify"
    return "error"



def build_main_graph(*, checkpointer: Any | None = None):
    """
    构建并编译主图（Main Graph）。
    此函数将所有相关的能力节点、入口节点和共享收尾节点注册到图上，并定义了节点之间的有向连接边及条件选择边。
    """
    graph = StateGraph(GraphState)

    graph.add_node("route_entry", route_entry)
    graph.add_node("chat_clarify", chat_clarify)
    graph.add_node("chat_collect_user_input", chat_collect_user_input)
    graph.add_node("chat_history_match", chat_history_match)
    graph.add_node("chat_review_task", chat_review_task)
    graph.add_node("chat_route_execution", chat_route_execution)
    graph.add_node("multi_dispatch_subgraph", build_multi_dispatch_subgraph())
    graph.add_node("normalize_pipeline_params", normalize_pipeline_params)
    graph.add_node("run_pipeline_node", run_pipeline_node)
    graph.add_node("collect_urls_node", collect_urls_node)
    graph.add_node("generate_config_node", generate_config_node)
    graph.add_node("batch_collect_node", batch_collect_node)
    graph.add_node("field_extract_node", field_extract_node)
    graph.add_node("plan_node", plan_node)
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
        resolve_chat_clarify_route,
        {
            "chat_collect_user_input": "chat_collect_user_input",
            "chat_history_match": "chat_history_match",
            "error": "build_artifact_index",
        },
    )
    graph.add_edge("chat_collect_user_input", "chat_clarify")
    graph.add_edge("chat_history_match", "chat_review_task")
    graph.add_conditional_edges(
        "chat_review_task",
        resolve_chat_review_route,
        {
            "chat_route_execution": "chat_route_execution",
            "chat_clarify": "chat_clarify",
            "error": "build_artifact_index",
        },
    )
    graph.add_conditional_edges(
        "chat_route_execution",
        resolve_node_outcome,
        {"ok": "plan_node", "error": "build_artifact_index"},
    )

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
        {"ok": "multi_dispatch_subgraph", "error": "build_artifact_index"},
    )
    graph.add_conditional_edges(
        "multi_dispatch_subgraph",
        resolve_node_outcome,
        {"ok": "aggregate_node", "error": "build_artifact_index"},
    )
    graph.add_edge("aggregate_node", "build_artifact_index")

    graph.add_edge("build_artifact_index", "build_summary")
    graph.add_edge("build_summary", "finalize_result")
    graph.add_edge("finalize_result", END)

    return graph.compile(checkpointer=checkpointer)

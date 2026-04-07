"""
MainGraph：主链路图编排。
该模块负责构建主状态图（Main Graph）。
对外正式入口收敛为 `chat_pipeline`，`pipeline_run` 仅保留为内部测试/脚本直连路径。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes.capability_nodes import (
    aggregate_node,
    plan_node,
    run_pipeline_node,
)
from .nodes.entry_nodes import (
    chat_clarify,
    chat_collect_user_input,
    chat_history_match,
    chat_review_task,
    chat_prepare_execution_handoff,
    normalize_pipeline_params,
    route_entry,
)
from .nodes.shared_nodes import build_artifact_index, build_summary, finalize_result
from .state import GraphState
from .subgraphs import build_multi_dispatch_subgraph



def resolve_entry_route(state: dict[str, Any]) -> str:
    """
    根据 entry_mode 选择图的入口分支。

    当前用户侧主路径是 `chat_pipeline`：先经过 chat 澄清/复用/review，
    再进入 planning 与 multi-dispatch。`pipeline_run` 仅保留为内部直连路径。
    """
    mapping = {
        "chat_pipeline": "chat_clarify",
        "pipeline_run": "normalize_pipeline_params",
    }

    mode = str(state.get("entry_mode") or "")
    if mode not in mapping:
        return "finalize_result"
    return mapping[mode]



def resolve_node_outcome(state: dict[str, Any]) -> str:
    """根据 node_status 选择图后续流向。"""
    if state.get("error"):
        return "error"
    planning = dict(state.get("planning") or {})
    dispatch = dict(state.get("dispatch") or {})
    result = dict(state.get("result") or {})
    stage_status = str(
        planning.get("status")
        or dispatch.get("status")
        or result.get("status")
        or state.get("node_status")
        or ""
    )
    if stage_status == "ok":
        return "ok"
    return "error"



def resolve_chat_clarify_route(state: dict[str, Any]) -> str:
    """根据 chat 澄清阶段结果选择后续节点。"""
    if state.get("error"):
        return "error"

    conversation = dict(state.get("conversation") or {})
    flow_state = str(conversation.get("flow_state") or state.get("chat_flow_state") or "")
    if flow_state == "needs_input":
        return "chat_collect_user_input"
    if flow_state == "ready":
        return "chat_history_match"
    return "error"



def resolve_chat_review_route(state: dict[str, Any]) -> str:
    """根据 chat review 阶段结果选择后续节点。"""
    if state.get("error"):
        return "error"

    conversation = dict(state.get("conversation") or {})
    review_state = str(conversation.get("review_state") or state.get("chat_review_state") or "")
    if review_state == "approved":
        return "chat_prepare_execution_handoff"
    if review_state == "reclarify":
        return "chat_clarify"
    return "error"



def build_main_graph(*, checkpointer: Any | None = None):
    """
    构建并编译主图（Main Graph）。
    此函数将所有相关的能力节点、入口节点和共享收尾节点注册到图上，并定义节点之间的连接关系。

    主交互链路固定为：chat 澄清 -> 历史任务复用 -> review -> planning handoff -> plan -> multi-dispatch。
    """
    graph = StateGraph(GraphState)

    graph.add_node("route_entry", route_entry)
    graph.add_node("chat_clarify", chat_clarify)
    graph.add_node("chat_collect_user_input", chat_collect_user_input)
    graph.add_node("chat_history_match", chat_history_match)
    graph.add_node("chat_review_task", chat_review_task)
    graph.add_node("chat_prepare_execution_handoff", chat_prepare_execution_handoff)
    graph.add_node("multi_dispatch_subgraph", build_multi_dispatch_subgraph())
    graph.add_node("normalize_pipeline_params", normalize_pipeline_params)
    graph.add_node("run_pipeline_node", run_pipeline_node)
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
            "chat_prepare_execution_handoff": "chat_prepare_execution_handoff",
            "chat_clarify": "chat_clarify",
            "error": "build_artifact_index",
        },
    )
    graph.add_conditional_edges(
        "chat_prepare_execution_handoff",
        resolve_node_outcome,
        {"ok": "plan_node", "error": "build_artifact_index"},
    )

    graph.add_conditional_edges(
        "normalize_pipeline_params",
        resolve_node_outcome,
        {"ok": "run_pipeline_node", "error": "build_artifact_index"},
    )
    graph.add_edge("run_pipeline_node", "build_artifact_index")

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

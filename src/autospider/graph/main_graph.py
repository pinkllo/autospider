"""
MainGraph：主链路图编排。
该模块负责构建主状态图（Main Graph）。
对外正式入口收敛为 `chat_pipeline`。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .nodes.capability_nodes import (
    aggregate_node,
    plan_node,
)
from .nodes.entry_nodes import (
    chat_clarify,
    chat_collect_user_input,
    chat_history_match,
    chat_review_task,
    chat_prepare_execution_handoff,
    route_entry,
)
from .nodes.feedback_nodes import monitor_dispatch_node, update_world_model_node
from .nodes.planning_nodes import initialize_world_model_node, plan_strategy_node
from .nodes.shared_nodes import build_artifact_index, build_summary, finalize_result
from .state import GraphState
from .state_access import (
    StageName,
    get_conversation_state,
    get_stage_status,
)
from .subgraphs import build_multi_dispatch_subgraph
from .subgraphs.multi_dispatch import route_after_feedback
from .workflow_access import coerce_workflow_state



def resolve_entry_route(state: dict[str, Any]) -> str:
    """
    根据 entry_mode 选择图的入口分支。

    当前用户侧主路径是 `chat_pipeline`：先经过 chat 澄清/复用/review，
    再进入 planning 与 multi-dispatch。
    """
    meta = dict(coerce_workflow_state(state).get("meta") or {})
    mode = str(meta.get("entry_mode") or state.get("entry_mode") or "")
    if mode != "chat_pipeline":
        return "finalize_result"
    return "chat_clarify"

def resolve_node_outcome(
    state: dict[str, Any],
    *,
    stage: StageName | None = None,
) -> str:
    """根据 node_status 选择图后续流向。"""
    if state.get("error"):
        return "error"
    stage_status = get_stage_status(state, stage=stage)
    if stage_status == "ok":
        return "ok"
    return "error"



def resolve_chat_clarify_route(state: dict[str, Any]) -> str:
    """根据 chat 澄清阶段结果选择后续节点。"""
    if state.get("error"):
        return "error"

    conversation = get_conversation_state(state)
    flow_state = str(conversation.get("flow_state") or "")
    if flow_state == "needs_input":
        return "chat_collect_user_input"
    if flow_state == "ready":
        return "chat_history_match"
    return "error"



def resolve_chat_review_route(state: dict[str, Any]) -> str:
    """根据 chat review 阶段结果选择后续节点。"""
    if state.get("error"):
        return "error"

    conversation = get_conversation_state(state)
    review_state = str(conversation.get("review_state") or "")
    if review_state == "approved":
        return "chat_prepare_execution_handoff"
    if review_state == "reclarify":
        return "chat_clarify"
    return "error"



def resolve_feedback_route(state: dict[str, Any]) -> str:
    """Map feedback decisions back into the next main-graph node."""
    if route_after_feedback(state) == "replan":
        return "plan_strategy_node"
    return "aggregate_node"


def _register_main_graph_nodes(graph: StateGraph) -> None:
    graph.add_node("route_entry", route_entry)
    graph.add_node("chat_clarify", chat_clarify)
    graph.add_node("chat_collect_user_input", chat_collect_user_input)
    graph.add_node("chat_history_match", chat_history_match)
    graph.add_node("chat_review_task", chat_review_task)
    graph.add_node("chat_prepare_execution_handoff", chat_prepare_execution_handoff)
    graph.add_node("initialize_world_model_node", initialize_world_model_node)
    graph.add_node("plan_strategy_node", plan_strategy_node)
    graph.add_node("multi_dispatch_subgraph", build_multi_dispatch_subgraph())
    graph.add_node("plan_node", plan_node)
    graph.add_node("monitor_dispatch_node", monitor_dispatch_node)
    graph.add_node("update_world_model_node", update_world_model_node)
    graph.add_node("aggregate_node", aggregate_node)
    graph.add_node("build_artifact_index", build_artifact_index)
    graph.add_node("build_summary", build_summary)
    graph.add_node("finalize_result", finalize_result)


def _add_entry_flow(graph: StateGraph) -> None:
    graph.set_entry_point("route_entry")
    graph.add_conditional_edges(
        "route_entry",
        resolve_entry_route,
        {
            "chat_clarify": "chat_clarify",
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


def _add_execution_flow(graph: StateGraph) -> None:
    graph.add_conditional_edges(
        "chat_prepare_execution_handoff",
        resolve_node_outcome,
        {"ok": "initialize_world_model_node", "error": "build_artifact_index"},
    )
    graph.add_edge("initialize_world_model_node", "plan_strategy_node")
    graph.add_edge("plan_strategy_node", "plan_node")
    graph.add_conditional_edges(
        "plan_node",
        lambda state: resolve_node_outcome(state, stage="planning"),
        {"ok": "multi_dispatch_subgraph", "error": "build_artifact_index"},
    )
    graph.add_conditional_edges(
        "multi_dispatch_subgraph",
        resolve_node_outcome,
        {"ok": "monitor_dispatch_node", "error": "build_artifact_index"},
    )
    graph.add_edge("monitor_dispatch_node", "update_world_model_node")
    graph.add_conditional_edges(
        "update_world_model_node",
        resolve_feedback_route,
        {
            "plan_strategy_node": "plan_strategy_node",
            "aggregate_node": "aggregate_node",
        },
    )
    graph.add_edge("aggregate_node", "build_artifact_index")
    graph.add_edge("build_artifact_index", "build_summary")
    graph.add_edge("build_summary", "finalize_result")
    graph.add_edge("finalize_result", END)


def build_main_graph(*, checkpointer: Any | None = None):
    """
    构建并编译主图（Main Graph）。
    此函数将所有相关的能力节点、入口节点和共享收尾节点注册到图上，并定义节点之间的连接关系。

    主交互链路固定为：chat 澄清 -> 历史任务复用 -> review -> planning handoff -> plan -> multi-dispatch。
    """
    graph = StateGraph(GraphState)

    _register_main_graph_nodes(graph)
    _add_entry_flow(graph)
    _add_execution_flow(graph)

    return graph.compile(checkpointer=checkpointer)

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from .subgraphs import build_multi_dispatch_subgraph
from .routes import (
    resolve_chat_clarify_route,
    resolve_chat_review_route,
    resolve_entry_route,
    resolve_feedback_route,
    resolve_node_outcome,
)

from .nodes.collect_nodes import monitor_dispatch_node, update_world_model_node
from .nodes.entry_nodes import (
    chat_clarify,
    chat_collect_user_input,
    chat_history_match,
    chat_prepare_execution_handoff,
    chat_review_task,
    route_entry,
)
from .nodes.finalize_nodes import (
    aggregate_node,
    build_artifact_index,
    build_summary,
    finalize_result,
)
from .nodes.plan_nodes import initialize_world_model_node, plan_node, plan_strategy_node
from .state import GraphState


def build_main_graph(*, checkpointer: Any | None = None):
    graph = StateGraph(GraphState)

    graph.add_node("route_entry", route_entry)
    graph.add_node("chat_clarify", chat_clarify)
    graph.add_node("chat_collect_user_input", chat_collect_user_input)
    graph.add_node("chat_history_match", chat_history_match)
    graph.add_node("chat_review_task", chat_review_task)
    graph.add_node("chat_prepare_execution_handoff", chat_prepare_execution_handoff)
    graph.add_node("initialize_world_model_node", initialize_world_model_node)
    graph.add_node("plan_strategy_node", plan_strategy_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("multi_dispatch_subgraph", build_multi_dispatch_subgraph())
    graph.add_node("monitor_dispatch_node", monitor_dispatch_node)
    graph.add_node("update_world_model_node", update_world_model_node)
    graph.add_node("aggregate_node", aggregate_node)
    graph.add_node("build_artifact_index", build_artifact_index)
    graph.add_node("build_summary", build_summary)
    graph.add_node("finalize_result", finalize_result)

    graph.set_entry_point("route_entry")
    graph.add_conditional_edges(
        "route_entry",
        resolve_entry_route,
        {"chat_clarify": "chat_clarify", "finalize_result": "finalize_result"},
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
        {"plan_strategy_node": "plan_strategy_node", "aggregate_node": "aggregate_node"},
    )
    graph.add_edge("aggregate_node", "build_artifact_index")
    graph.add_edge("build_artifact_index", "build_summary")
    graph.add_edge("build_summary", "finalize_result")
    graph.add_edge("finalize_result", END)
    return graph.compile(checkpointer=checkpointer)

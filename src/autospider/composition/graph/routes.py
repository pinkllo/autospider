from __future__ import annotations

from typing import Any

from autospider.composition.graph._multi_dispatch import route_after_feedback
from autospider.composition.graph.state_access import conversation_state, get_stage_status
from autospider.composition.graph.workflow_access import coerce_workflow_state


def resolve_entry_route(state: dict[str, Any]) -> str:
    meta = dict(coerce_workflow_state(state).get("meta") or {})
    mode = str(meta.get("entry_mode") or state.get("entry_mode") or "")
    if mode != "chat_pipeline":
        return "finalize_result"
    return "chat_clarify"


def resolve_node_outcome(
    state: dict[str, Any],
    *,
    stage: str | None = None,
) -> str:
    if state.get("error"):
        return "error"
    stage_status = get_stage_status(state, stage=stage)
    if stage_status == "ok":
        return "ok"
    return "error"


def resolve_chat_clarify_route(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "error"

    conversation = conversation_state(state)
    flow_state = str(conversation.get("flow_state") or "")
    if flow_state == "needs_input":
        return "chat_collect_user_input"
    if flow_state == "ready":
        return "chat_history_match"
    return "error"


def resolve_chat_review_route(state: dict[str, Any]) -> str:
    if state.get("error"):
        return "error"

    conversation = conversation_state(state)
    review_state = str(conversation.get("review_state") or "")
    if review_state == "approved":
        return "chat_prepare_execution_handoff"
    if review_state == "reclarify":
        return "chat_clarify"
    return "error"


def resolve_feedback_route(state: dict[str, Any]) -> str:
    if route_after_feedback(state) == "replan":
        return "plan_strategy_node"
    return "aggregate_node"

__all__ = [
    "resolve_chat_clarify_route",
    "resolve_chat_review_route",
    "resolve_entry_route",
    "resolve_feedback_route",
    "resolve_node_outcome",
]

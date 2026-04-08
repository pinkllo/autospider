"""LangGraph state shells."""

from __future__ import annotations

from typing import Any, TypedDict

from .types import EntryMode, NodeStatus


class StageErrorState(TypedDict, total=False):
    code: str
    message: str


class ConversationState(TypedDict, total=False):
    status: NodeStatus
    flow_state: str
    review_state: str
    clarified_task: dict[str, Any] | None
    chat_history: list[dict[str, str]]
    chat_turn_count: int
    chat_max_turns: int
    pending_question: str
    matched_skills: list[dict[str, str]]
    selected_skills: list[dict[str, str]]
    payload: dict[str, Any]
    error: StageErrorState | None


class PlanningState(TypedDict, total=False):
    status: NodeStatus
    task_plan: Any
    plan_knowledge: str
    selected_skills: list[dict[str, str]]
    summary: dict[str, Any]
    payload: dict[str, Any]
    error: StageErrorState | None


class DispatchState(TypedDict, total=False):
    status: NodeStatus
    task_plan: Any
    plan_knowledge: str
    dispatch_result: dict[str, Any]
    subtask_results: list[dict[str, Any]]
    summary: dict[str, Any]
    payload: dict[str, Any]
    error: StageErrorState | None


class ResultState(TypedDict, total=False):
    status: NodeStatus
    data: dict[str, Any]
    summary: dict[str, Any]
    artifacts: list[dict[str, str]]
    payload: dict[str, Any]
    error: StageErrorState | None


class GraphState(TypedDict, total=False):
    thread_id: str
    request_id: str
    entry_mode: EntryMode
    cli_args: dict[str, Any]
    normalized_params: dict[str, Any]
    conversation: ConversationState
    planning: PlanningState
    dispatch: DispatchState
    result: ResultState
    error: StageErrorState | None
    artifacts: list[dict[str, str]]
    summary: dict[str, Any]
    status: str
    error_code: str
    error_message: str
    clarified_task: dict[str, Any] | None
    chat_history: list[dict[str, str]]
    chat_turn_count: int
    chat_max_turns: int
    chat_pending_question: str
    chat_flow_state: str
    chat_review_state: str
    matched_skills: list[dict[str, str]]
    selected_skills: list[dict[str, str]]
    history_match_done: bool
    history_match_signature: str
    task_plan: Any
    plan_knowledge: str
    dispatch_result: dict[str, Any]
    subtask_results: list[dict[str, Any]]
    node_status: NodeStatus
    node_payload: dict[str, Any]
    node_artifacts: list[dict[str, str]]
    node_error: StageErrorState | None

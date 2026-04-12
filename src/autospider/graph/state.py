"""LangGraph state shells."""

from __future__ import annotations

from typing import Any, TypedDict

from ..domain.runtime import SubTaskRuntimeState
from .types import EntryMode, NodeStatus
from .workflow_state import (
    WorkflowControlState,
    WorkflowExecutionState,
    WorkflowIntentState,
    WorkflowMetaState,
    WorkflowResultState,
    WorkflowState,
    WorkflowWorldState,
)


class StageErrorState(TypedDict, total=False):
    code: str
    message: str


class ConversationState(TypedDict, total=False):
    status: NodeStatus
    flow_state: str
    review_state: str
    normalized_params: dict[str, Any]
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
    subtask_results: list[SubTaskRuntimeState]
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
    final_error: StageErrorState | None


class GraphState(TypedDict, total=False):
    meta: WorkflowMetaState
    intent: WorkflowIntentState
    world: WorkflowWorldState
    control: WorkflowControlState
    execution: WorkflowExecutionState
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
    history_match_done: bool
    history_match_signature: str
    task_plan: Any
    plan_knowledge: str
    dispatch_result: dict[str, Any]
    subtask_results: list[SubTaskRuntimeState]
    node_status: NodeStatus
    node_payload: dict[str, Any]
    node_artifacts: list[dict[str, str]]
    node_error: StageErrorState | None


__all__ = [
    "ConversationState",
    "DispatchState",
    "GraphState",
    "PlanningState",
    "ResultState",
    "StageErrorState",
    "WorkflowControlState",
    "WorkflowExecutionState",
    "WorkflowIntentState",
    "WorkflowMetaState",
    "WorkflowResultState",
    "WorkflowState",
    "WorkflowWorldState",
]

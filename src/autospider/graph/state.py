"""LangGraph state shells."""

from __future__ import annotations

from typing import Any, TypedDict

from .types import EntryMode, NodeStatus


class StageErrorState(TypedDict, total=False):
    code: str
    message: str


class ConversationState(TypedDict, total=False):
    status: NodeStatus
    payload: dict[str, Any]
    error: StageErrorState | None


class PlanningState(TypedDict, total=False):
    status: NodeStatus
    payload: dict[str, Any]
    error: StageErrorState | None


class DispatchState(TypedDict, total=False):
    status: NodeStatus
    payload: dict[str, Any]
    error: StageErrorState | None


class ResultState(TypedDict, total=False):
    status: NodeStatus
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
    node_status: NodeStatus
    node_payload: dict[str, Any]
    node_artifacts: list[dict[str, str]]
    node_error: StageErrorState | None

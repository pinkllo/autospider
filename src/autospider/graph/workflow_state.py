"""Canonical workflow-shaped state contracts."""

from __future__ import annotations

from typing import Any, TypedDict

from ..domain.runtime import SubTaskRuntimeState
from .types import EntryMode


class WorkflowErrorState(TypedDict, total=False):
    code: str
    message: str


class WorkflowMetaState(TypedDict, total=False):
    thread_id: str
    request_id: str
    entry_mode: EntryMode


class WorkflowIntentState(TypedDict, total=False):
    fields: list[dict[str, Any]]
    clarified_task: dict[str, Any] | None


class WorkflowWorldState(TypedDict, total=False):
    request_params: dict[str, Any]
    collection_config: dict[str, Any]


class WorkflowControlState(TypedDict, total=False):
    current_plan: Any
    stage_status: str


class WorkflowExecutionState(TypedDict, total=False):
    dispatch_summary: dict[str, Any]
    subtask_results: list[SubTaskRuntimeState]


class WorkflowResultState(TypedDict, total=False):
    data: dict[str, Any]
    summary: dict[str, Any]
    artifacts: list[dict[str, str]]
    final_error: WorkflowErrorState | None


class WorkflowState(TypedDict, total=False):
    meta: WorkflowMetaState
    intent: WorkflowIntentState
    world: WorkflowWorldState
    control: WorkflowControlState
    execution: WorkflowExecutionState
    result: WorkflowResultState

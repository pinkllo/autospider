"""LangGraph 状态定义。"""

from __future__ import annotations

from typing import Any, TypedDict

from .types import EntryMode, NodeStatus


class GraphState(TypedDict, total=False):
    """主图状态。"""

    entry_mode: EntryMode
    thread_id: str
    request_id: str
    invoked_at: str
    cli_args: dict[str, Any]

    normalized_params: dict[str, Any]
    clarified_task: dict[str, Any] | None
    chat_history: list[dict[str, str]]
    chat_turn_count: int
    chat_max_turns: int
    chat_pending_question: str
    chat_flow_state: str
    chat_review_state: str
    task_plan: Any
    dispatch_queue: list[dict[str, Any]]
    current_batch: list[dict[str, Any]]
    spawned_subtasks: list[dict[str, Any]]
    subtask_results: list[dict[str, Any]]
    dispatch_result: dict[str, Any]
    aggregate_result: dict[str, Any]

    node_status: NodeStatus
    node_payload: dict[str, Any]
    node_artifacts: list[dict[str, str]]
    node_error: dict[str, str] | None

    artifacts: list[dict[str, str]]
    summary: dict[str, Any]
    status: str
    error_code: str
    error_message: str

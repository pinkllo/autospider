"""LangGraph 状态定义。"""

from __future__ import annotations

from typing import Any, TypedDict

from .types import EntryMode, NodeStatus


class GraphState(TypedDict, total=False):
    """主图状态。"""

    entry_mode: EntryMode
    request_id: str
    invoked_at: str
    cli_args: dict[str, Any]

    normalized_params: dict[str, Any]
    clarified_task: dict[str, Any] | None
    task_plan: Any
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

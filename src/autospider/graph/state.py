"""LangGraph 状态定义。"""

from __future__ import annotations

from typing import Any, TypedDict

from .types import EntryMode, NodeStatus


class GraphState(TypedDict, total=False):
    """主图状态。"""

    # 会话 / 入口状态
    entry_mode: EntryMode
    thread_id: str
    request_id: str
    invoked_at: str
    cli_args: dict[str, Any]

    # chat 交互状态
    normalized_params: dict[str, Any]
    clarified_task: dict[str, Any] | None
    chat_history: list[dict[str, str]]
    chat_turn_count: int
    chat_max_turns: int
    chat_pending_question: str
    chat_flow_state: str
    chat_review_state: str
    history_match_done: bool
    matched_skills: list[dict[str, str]]
    selected_skills: list[dict[str, str]]

    # direct pipeline 状态（兼容 / 内部路径）
    collection_config: dict[str, Any]
    collection_progress: dict[str, Any]
    collected_urls: list[str]
    fields_config: list[dict[str, Any]]
    xpath_result: dict[str, Any] | None
    pipeline_result: dict[str, Any]

    # planning / dispatch / aggregate 状态
    task_plan: Any
    plan_knowledge: str
    dispatch_queue: list[dict[str, Any]]
    current_batch: list[dict[str, Any]]
    spawned_subtasks: list[dict[str, Any]]
    subtask_results: list[dict[str, Any]]
    dispatch_result: dict[str, Any]
    aggregate_result: dict[str, Any]

    # 通用节点输出状态
    node_status: NodeStatus
    node_payload: dict[str, Any]
    node_artifacts: list[dict[str, str]]
    node_error: dict[str, str] | None

    # 全局收尾状态
    artifacts: list[dict[str, str]]
    summary: dict[str, Any]
    status: str
    error_code: str
    error_message: str

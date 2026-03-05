"""入口与参数归一化节点。"""

from __future__ import annotations

import dataclasses
from typing import Any

import typer

from ...common.llm import ClarifiedTask, DialogueMessage, TaskClarifier
from ...field import FieldDefinition


def _ok(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "node_status": "ok",
        "node_payload": payload or {},
        "node_artifacts": [],
        "node_error": None,
    }


def _fatal(code: str, message: str) -> dict[str, Any]:
    return {
        "node_status": "fatal",
        "node_payload": {},
        "node_artifacts": [],
        "node_error": {"code": code, "message": message},
        "error_code": code,
        "error_message": message,
    }


def _resolve_chat_execution_mode(mode: str) -> str:
    normalized = (mode or "auto").strip().lower()
    if normalized in {"single", "multi"}:
        return normalized
    return "multi"


def _field_to_dict(field: Any) -> dict[str, Any]:
    if isinstance(field, FieldDefinition):
        return dataclasses.asdict(field)
    if isinstance(field, dict):
        return {
            "name": str(field.get("name") or ""),
            "description": str(field.get("description") or ""),
            "required": bool(field.get("required", True)),
            "data_type": str(field.get("data_type") or "text"),
            "example": field.get("example"),
        }
    return {}


def _clarified_task_to_dict(task: ClarifiedTask) -> dict[str, Any]:
    return {
        "intent": task.intent,
        "list_url": task.list_url,
        "task_description": task.task_description,
        "fields": [_field_to_dict(field) for field in task.fields],
        "max_pages": task.max_pages,
        "target_url_count": task.target_url_count,
        "consumer_concurrency": task.consumer_concurrency,
        "field_explore_count": task.field_explore_count,
        "field_validate_count": task.field_validate_count,
    }


def route_entry(state: dict[str, Any]) -> dict[str, Any]:
    """入口路由节点。"""
    mode = state.get("entry_mode")
    if not mode:
        return _fatal("missing_entry_mode", "缺少 entry_mode")
    valid_modes = {
        "chat_pipeline",
        "pipeline_run",
        "collect_urls",
        "generate_config",
        "batch_collect",
        "field_extract",
        "multi_pipeline",
    }
    if str(mode) not in valid_modes:
        return _fatal("invalid_entry_mode", f"不支持的 entry_mode: {mode}")
    return {
        **_ok({"entry_mode": mode}),
        "normalized_params": dict(state.get("cli_args") or {}),
    }


def normalize_pipeline_params(state: dict[str, Any]) -> dict[str, Any]:
    """pipeline-run 参数归一化。"""
    return {
        **_ok({"normalized": True}),
        "normalized_params": dict(state.get("cli_args") or {}),
    }


async def chat_clarify(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 澄清节点。"""
    cli_args = dict(state.get("cli_args") or {})
    clarified_task = cli_args.get("clarified_task")
    if isinstance(clarified_task, dict):
        return {
            **_ok({"clarified": True, "source": "cli"}),
            "clarified_task": clarified_task,
        }

    initial_request = str(cli_args.get("request") or "").strip()
    if not initial_request:
        return _fatal("empty_request", "chat-pipeline 缺少初始需求")

    max_turns = int(cli_args.get("max_turns") or 6)
    interactive = bool(cli_args.get("interactive", True))
    history: list[DialogueMessage] = [DialogueMessage(role="user", content=initial_request)]

    clarifier = TaskClarifier()
    for _ in range(max_turns):
        result = await clarifier.clarify(history)
        if result.status == "reject":
            return _fatal("clarifier_reject", result.reason or "该任务暂不支持自动执行")

        if result.status == "ready" and result.task is not None:
            return {
                **_ok({"clarified": True, "source": "llm"}),
                "clarified_task": _clarified_task_to_dict(result.task),
            }

        question = result.next_question or "请补充更明确的采集目标、URL 或字段要求。"
        if not interactive:
            return _fatal("clarifier_incomplete", question)

        answer = typer.prompt(question).strip()
        if not answer:
            answer = "请按常见默认方案继续，并明确你的默认假设。"
        history.append(DialogueMessage(role="assistant", content=question))
        history.append(DialogueMessage(role="user", content=answer))

    return _fatal("clarifier_incomplete", "在限定轮数内仍未澄清完成")


def chat_route_execution(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 执行策略路由。"""
    cli_args = dict(state.get("cli_args") or {})
    task = dict(state.get("clarified_task") or {})
    if not task:
        return _fatal("missing_clarified_task", "缺少澄清任务配置")

    resolved_mode = _resolve_chat_execution_mode(str(cli_args.get("execution_mode") or "auto"))
    normalized = {
        "list_url": task.get("list_url", ""),
        "task_description": task.get("task_description", ""),
        "fields": [_field_to_dict(item) for item in task.get("fields", [])],
        "max_pages": cli_args.get("max_pages", task.get("max_pages")),
        "target_url_count": cli_args.get(
            "target_url_count",
            task.get("target_url_count"),
        ),
        "consumer_concurrency": cli_args.get(
            "consumer_concurrency",
            task.get("consumer_concurrency"),
        ),
        "field_explore_count": cli_args.get(
            "field_explore_count",
            task.get("field_explore_count"),
        ),
        "field_validate_count": cli_args.get(
            "field_validate_count",
            task.get("field_validate_count"),
        ),
        "pipeline_mode": cli_args.get("pipeline_mode"),
        "headless": bool(cli_args.get("headless", False)),
        "output_dir": str(cli_args.get("output_dir") or "output"),
        "request": str(cli_args.get("request") or task.get("task_description") or ""),
        "max_concurrent": cli_args.get(
            "max_concurrent",
            cli_args.get("consumer_concurrency", task.get("consumer_concurrency")),
        ),
        "execution_mode_resolved": resolved_mode,
        "runtime_subtasks": cli_args.get("runtime_subtasks"),
        "runtime_subtask_max_depth": cli_args.get("runtime_subtask_max_depth"),
        "runtime_subtask_max_children": cli_args.get("runtime_subtask_max_children"),
        "runtime_subtasks_use_main_model": cli_args.get("runtime_subtasks_use_main_model"),
    }

    return {
        **_ok({"execution_mode_resolved": resolved_mode}),
        "normalized_params": normalized,
    }

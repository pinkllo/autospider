"""入口与参数归一化节点。"""

from __future__ import annotations

import dataclasses
from typing import Any

from langgraph.types import interrupt

from ...common.llm import TaskClarifier
from ...domain.chat import ClarifiedTask, DialogueMessage
from ...domain.fields import FieldDefinition
from ...common.validators import validate_task_description, validate_url

_DEFAULT_CHAT_FALLBACK = "请按常见默认方案继续，并明确你的默认假设。"


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



def _resolve_chat_execution_mode(mode: str | None = None) -> str:
    _ = mode
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



def _history_from_state(raw_history: Any, initial_request: str) -> list[DialogueMessage]:
    history: list[DialogueMessage] = []
    if isinstance(raw_history, list):
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role and content:
                history.append(DialogueMessage(role=role, content=content))
    if history:
        return history
    if initial_request:
        return [DialogueMessage(role="user", content=initial_request)]
    return []



def _history_to_state(history: list[DialogueMessage]) -> list[dict[str, str]]:
    return [{"role": item.role, "content": item.content} for item in history]



def _to_non_negative_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        number = int(value)
        return number if number >= 0 else default
    except (TypeError, ValueError):
        return default



def _to_positive_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        number = int(value)
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default



def _normalize_resume_answer(payload: Any) -> str:
    if isinstance(payload, dict):
        answer = payload.get("answer")
        if answer is None:
            answer = payload.get("message")
        return str(answer or "").strip()
    return str(payload or "").strip()



def _normalize_override_task(raw_task: Any) -> dict[str, Any]:
    if not isinstance(raw_task, dict):
        raise ValueError("override_task.task 必须是对象")

    normalized_fields: list[dict[str, Any]] = []
    for item in list(raw_task.get("fields") or []):
        field = _field_to_dict(item)
        if not field.get("name") or not field.get("description"):
            continue
        normalized_fields.append(field)

    if not normalized_fields:
        raise ValueError("字段不能为空")

    return {
        "intent": str(raw_task.get("intent") or "").strip(),
        "list_url": validate_url(str(raw_task.get("list_url") or "")),
        "task_description": validate_task_description(str(raw_task.get("task_description") or "")),
        "fields": normalized_fields,
        "max_pages": raw_task.get("max_pages"),
        "target_url_count": raw_task.get("target_url_count"),
        "consumer_concurrency": raw_task.get("consumer_concurrency"),
        "field_explore_count": raw_task.get("field_explore_count"),
        "field_validate_count": raw_task.get("field_validate_count"),
    }



def _build_review_payload(
    *,
    state: dict[str, Any],
    task: dict[str, Any],
    resolved_mode: str,
) -> dict[str, Any]:
    cli_args = dict(state.get("cli_args") or {})
    effective_options = {
        "max_pages": cli_args.get("max_pages", task.get("max_pages")),
        "target_url_count": cli_args.get("target_url_count", task.get("target_url_count")),
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
        "pipeline_mode": cli_args.get("pipeline_mode") or "默认",
        "execution_mode": resolved_mode,
        "headless": bool(cli_args.get("headless", False)),
        "output_dir": str(cli_args.get("output_dir") or "output"),
        "max_concurrent": cli_args.get(
            "max_concurrent",
            cli_args.get("consumer_concurrency", task.get("consumer_concurrency")),
        ),
    }
    return {
        "type": "chat_review",
        "thread_id": str(state.get("thread_id") or ""),
        "clarified_task": task,
        "effective_options": effective_options,
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
    clarified_task = state.get("clarified_task")
    if isinstance(clarified_task, dict) and clarified_task:
        return {
            **_ok({"clarified": True, "source": "state"}),
            "clarified_task": clarified_task,
            "chat_flow_state": "ready",
        }

    cli_args = dict(state.get("cli_args") or {})
    initial_request = str(cli_args.get("request") or "").strip()
    history = _history_from_state(state.get("chat_history"), initial_request)
    if not history:
        return _fatal("empty_request", "chat-pipeline 缺少初始需求")

    max_turns = _to_positive_int(state.get("chat_max_turns"), _to_positive_int(cli_args.get("max_turns"), 6))
    turn_count = _to_non_negative_int(state.get("chat_turn_count"), 0)

    clarifier = TaskClarifier()
    result = await clarifier.clarify(history)
    if result.status == "reject":
        return _fatal("clarifier_reject", result.reason or "该任务暂不支持自动执行")

    if result.status == "ready" and result.task is not None:
        return {
            **_ok({"clarified": True, "source": "llm"}),
            "clarified_task": _clarified_task_to_dict(result.task),
            "chat_history": _history_to_state(history),
            "chat_turn_count": turn_count,
            "chat_max_turns": max_turns,
            "chat_pending_question": "",
            "chat_flow_state": "ready",
        }

    if turn_count >= max_turns:
        return _fatal("clarifier_incomplete", "在限定轮数内仍未澄清完成")

    question = result.next_question or "请补充更明确的采集目标、URL 或字段要求。"
    return {
        **_ok({"clarified": False, "next_question": question}),
        "chat_history": _history_to_state(history),
        "chat_turn_count": turn_count + 1,
        "chat_max_turns": max_turns,
        "chat_pending_question": question,
        "chat_flow_state": "needs_input",
    }


async def chat_collect_user_input(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 人工回答节点。"""
    cli_args = dict(state.get("cli_args") or {})
    initial_request = str(cli_args.get("request") or "").strip()
    question = str(state.get("chat_pending_question") or "").strip()
    if not question:
        return _fatal("missing_clarification_question", "缺少待回答的澄清问题")

    history = _history_from_state(state.get("chat_history"), initial_request)
    turn_count = _to_non_negative_int(state.get("chat_turn_count"), 0)
    max_turns = _to_positive_int(state.get("chat_max_turns"), _to_positive_int(cli_args.get("max_turns"), 6))
    answer_payload = interrupt(
        {
            "type": "chat_clarification",
            "thread_id": str(state.get("thread_id") or ""),
            "question": question,
            "turn": turn_count,
            "max_turns": max_turns,
        }
    )
    answer = _normalize_resume_answer(answer_payload) or _DEFAULT_CHAT_FALLBACK

    history.append(DialogueMessage(role="assistant", content=question))
    history.append(DialogueMessage(role="user", content=answer))
    return {
        **_ok({"answer_collected": True}),
        "chat_history": _history_to_state(history),
        "chat_pending_question": "",
        "chat_flow_state": "input_collected",
    }


async def chat_review_task(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 执行前确认节点。"""
    cli_args = dict(state.get("cli_args") or {})
    initial_request = str(cli_args.get("request") or "").strip()
    task = dict(state.get("clarified_task") or {})
    if not task:
        return _fatal("missing_clarified_task", "缺少澄清任务配置")

    resolved_mode = _resolve_chat_execution_mode()
    review_payload = interrupt(_build_review_payload(state=state, task=task, resolved_mode=resolved_mode))
    action_payload = review_payload if isinstance(review_payload, dict) else {"action": review_payload}
    action = str(action_payload.get("action") or "approve").strip().lower()

    if action in {"approve", "start", "execute"}:
        return {
            **_ok({"review_action": action}),
            "chat_review_state": "approved",
        }

    if action == "supplement":
        supplement = _normalize_resume_answer(action_payload) or _DEFAULT_CHAT_FALLBACK
        history = _history_from_state(state.get("chat_history"), initial_request)
        history.append(DialogueMessage(role="user", content=supplement))
        return {
            **_ok({"review_action": action}),
            "chat_history": _history_to_state(history),
            "clarified_task": None,
            "chat_review_state": "reclarify",
            "chat_flow_state": "input_collected",
        }

    if action == "override_task":
        try:
            override_task = _normalize_override_task(action_payload.get("task"))
        except Exception as exc:  # noqa: BLE001
            return _fatal("invalid_override_task", str(exc))
        return {
            **_ok({"review_action": action}),
            "clarified_task": override_task,
            "chat_review_state": "approved",
        }

    if action == "cancel":
        return _fatal("chat_cancelled", "用户取消执行")

    return _fatal("invalid_review_action", f"不支持的 review action: {action}")



def chat_route_execution(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 执行策略路由。"""
    cli_args = dict(state.get("cli_args") or {})
    task = dict(state.get("clarified_task") or {})
    if not task:
        return _fatal("missing_clarified_task", "缺少澄清任务配置")

    resolved_mode = _resolve_chat_execution_mode()
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
        "runtime_subtask_max_children": cli_args.get("runtime_subtask_max_children"),
        "runtime_subtasks_use_main_model": cli_args.get("runtime_subtasks_use_main_model"),
    }

    return {
        **_ok({"execution_mode_resolved": "multi"}),
        "normalized_params": normalized,
    }

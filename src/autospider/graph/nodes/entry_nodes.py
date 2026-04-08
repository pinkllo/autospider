"""入口与参数归一化节点。"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from ...common.config import config
from ...common.experience import SkillRuntime
from ...common.llm import TaskClarifier
from ...common.llm.streaming import ainvoke_with_stream
from ...common.logger import get_logger
from ...common.protocol import extract_json_dict_from_llm_payload
from ...common.storage.task_run_query_service import TaskRunQueryService
from ...domain.chat import ClarifiedTask, DialogueMessage
from ...domain.fields import FieldDefinition
from ...common.validators import validate_task_description, validate_url
from ...pipeline.runtime_controls import resolve_concurrency_settings

logger = get_logger(__name__)

_DEFAULT_CHAT_FALLBACK = "请按常见默认方案继续，并明确你的默认假设。"
_MAX_HISTORY_CANDIDATES = 3
_URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")


def _ok(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_payload = payload or {}
    return {
        "node_status": "ok",
        "node_payload": resolved_payload,
        "result_context": resolved_payload,
        "node_artifacts": [],
        "node_error": None,
        "error": None,
    }



def _fatal(code: str, message: str) -> dict[str, Any]:
    return {
        "node_status": "fatal",
        "node_payload": {},
        "result_context": {},
        "node_artifacts": [],
        "node_error": {"code": code, "message": message},
        "error_code": code,
        "error_message": message,
        "error": {"code": code, "message": message},
    }



def _resolve_chat_dispatch_mode(mode: str | None = None) -> str:
    """chat 主路径当前固定进入 planning + multi-dispatch。"""
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


def _extract_urls_from_history(history: list[DialogueMessage]) -> list[str]:
    """从对话历史中提取 URL，保留出现顺序。"""
    seen: set[str] = set()
    urls: list[str] = []
    for item in history:
        text = str(item.content or "")
        for raw in _URL_PATTERN.findall(text):
            candidate = raw.rstrip(").,;!?]}>\"'")
            try:
                normalized = validate_url(candidate)
            except Exception:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            urls.append(normalized)
    return urls


def _serialize_skill_metadata(items: list[Any]) -> list[dict[str, str]]:
    """将 SkillMetadata 序列化为可入图状态的字典。"""
    serialized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in items:
        path = str(getattr(item, "path", "") or "")
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        serialized.append({
            "name": str(getattr(item, "name", "") or ""),
            "description": str(getattr(item, "description", "") or ""),
            "path": path,
            "domain": str(getattr(item, "domain", "") or ""),
        })
    return serialized


def _latest_history_url(history: list[DialogueMessage]) -> str:
    """取历史中最新一个合法 URL。"""
    urls = _extract_urls_from_history(history)
    if not urls:
        return ""
    return urls[-1]



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



def _coalesce_cli_option(cli_args: dict[str, Any], key: str, fallback: Any) -> Any:
    """CLI 显式传值优先；CLI 为 None 时保留上游已解析出的任务参数。"""
    value = cli_args.get(key)
    return fallback if value is None else value


def _conversation_state(state: dict[str, Any]) -> dict[str, Any]:
    return dict(state.get("conversation") or {})


def _conversation_value(state: dict[str, Any], key: str, default: Any = None) -> Any:
    return _conversation_state(state).get(key, default)


def _is_serial_mode_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_serial_mode_overrides(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params or {})
    serial_mode = _is_serial_mode_enabled(normalized.get("serial_mode"))
    normalized["serial_mode"] = serial_mode
    if not serial_mode:
        return normalized
    normalized["consumer_concurrency"] = 1
    normalized["max_concurrent"] = 1
    return normalized


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
    dispatch_mode: str,
) -> dict[str, Any]:
    cli_args = dict(state.get("cli_args") or {})
    base_options = _apply_serial_mode_overrides({
        "max_pages": _coalesce_cli_option(cli_args, "max_pages", task.get("max_pages")),
        "target_url_count": _coalesce_cli_option(cli_args, "target_url_count", task.get("target_url_count")),
        "consumer_concurrency": _coalesce_cli_option(
            cli_args,
            "consumer_concurrency",
            task.get("consumer_concurrency"),
        ),
        "field_explore_count": _coalesce_cli_option(
            cli_args,
            "field_explore_count",
            task.get("field_explore_count"),
        ),
        "field_validate_count": _coalesce_cli_option(
            cli_args,
            "field_validate_count",
            task.get("field_validate_count"),
        ),
        "pipeline_mode": cli_args.get("pipeline_mode") or "默认",
        "execution_mode": dispatch_mode,
        "headless": cli_args["headless"] if "headless" in cli_args else None,
        "output_dir": str(cli_args.get("output_dir") or "output"),
        "serial_mode": cli_args.get("serial_mode"),
        "max_concurrent": _coalesce_cli_option(cli_args, "max_concurrent", None),
        "global_browser_budget": cli_args.get("global_browser_budget"),
    })
    concurrency = resolve_concurrency_settings(base_options)
    effective_options = dict(base_options)
    effective_options["consumer_concurrency"] = concurrency.consumer_concurrency
    effective_options["max_concurrent"] = concurrency.max_concurrent
    effective_options["global_browser_budget"] = concurrency.global_browser_budget
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
    if str(mode) != "chat_pipeline":
        return _fatal("invalid_entry_mode", f"不支持的 entry_mode: {mode}")
    return {
        **_ok({"entry_mode": mode}),
        "normalized_params": _apply_serial_mode_overrides(dict(state.get("cli_args") or {})),
    }



def normalize_pipeline_params(state: dict[str, Any]) -> dict[str, Any]:
    """执行参数归一化。"""
    normalized = _apply_serial_mode_overrides(dict(state.get("cli_args") or {}))
    return {
        **_ok({"normalized": True}),
        "normalized_params": normalized,
        "conversation": {"status": "ok", "normalized_params": normalized},
    }


async def chat_clarify(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 澄清节点。"""
    clarified_task = _conversation_value(state, "clarified_task")
    if isinstance(clarified_task, dict) and clarified_task:
        return {
            **_ok({"clarified": True, "source": "state"}),
            "conversation": {"status": "ok", "flow_state": "ready", "clarified_task": clarified_task},
        }

    cli_args = dict(state.get("cli_args") or {})
    initial_request = str(cli_args.get("request") or "").strip()
    history = _history_from_state(_conversation_value(state, "chat_history"), initial_request)
    if not history:
        return _fatal("empty_request", "chat-pipeline 缺少初始需求")

    max_turns = _to_positive_int(_conversation_value(state, "chat_max_turns"), _to_positive_int(cli_args.get("max_turns"), 6))
    turn_count = _to_non_negative_int(_conversation_value(state, "chat_turn_count"), 0)
    clarifier = TaskClarifier()
    runtime = SkillRuntime()
    latest_url = _latest_history_url(history)
    matched_skill_meta = runtime.discover_by_url(latest_url) if latest_url else []
    matched_skills = _serialize_skill_metadata(matched_skill_meta)
    selected_skill_meta = await runtime.get_or_select(
        phase="clarifier",
        url=latest_url,
        task_context={
            "request": initial_request,
            "history": _history_to_state(history),
        },
        llm=clarifier.llm,
    ) if latest_url else []
    selected_skills = _serialize_skill_metadata(selected_skill_meta)
    selected_context = runtime.format_selected_skills_context(
        runtime.load_selected_bodies(selected_skill_meta)
    )

    result = await clarifier.clarify(
        history,
        available_skills=matched_skills,
        selected_skills=selected_skills,
        selected_skills_context=selected_context,
    )
    if result.status == "reject":
        return _fatal("clarifier_reject", result.reason or "该任务暂不支持自动执行")

    if result.status == "ready" and result.task is not None:
        clarified_payload = _clarified_task_to_dict(result.task)
        return {
            **_ok({"clarified": True, "source": "llm"}),
            "conversation": {
                "status": "ok",
                "flow_state": "ready",
                "clarified_task": clarified_payload,
                "chat_history": _history_to_state(history),
                "chat_turn_count": turn_count,
                "chat_max_turns": max_turns,
                "pending_question": "",
                "matched_skills": matched_skills,
                "selected_skills": selected_skills,
            },
        }

    if turn_count >= max_turns:
        return _fatal("clarifier_incomplete", "在限定轮数内仍未澄清完成")

    question = result.next_question or "请补充更明确的采集目标、URL 或字段要求。"
    return {
        **_ok({"clarified": False, "next_question": question}),
        "conversation": {
            "status": "ok",
            "flow_state": "needs_input",
            "chat_history": _history_to_state(history),
            "chat_turn_count": turn_count + 1,
            "chat_max_turns": max_turns,
            "pending_question": question,
            "matched_skills": matched_skills,
            "selected_skills": selected_skills,
        },
    }


async def chat_collect_user_input(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 人工回答节点。"""
    cli_args = dict(state.get("cli_args") or {})
    initial_request = str(cli_args.get("request") or "").strip()
    question = str(_conversation_value(state, "pending_question") or "").strip()
    if not question:
        return _fatal("missing_clarification_question", "缺少待回答的澄清问题")

    history = _history_from_state(_conversation_value(state, "chat_history"), initial_request)
    turn_count = _to_non_negative_int(_conversation_value(state, "chat_turn_count"), 0)
    max_turns = _to_positive_int(_conversation_value(state, "chat_max_turns"), _to_positive_int(cli_args.get("max_turns"), 6))
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
        "conversation": {
            "status": "ok",
            "flow_state": "input_collected",
            "chat_history": _history_to_state(history),
            "pending_question": "",
        },
    }


async def chat_review_task(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 执行前确认节点。"""
    cli_args = dict(state.get("cli_args") or {})
    initial_request = str(cli_args.get("request") or "").strip()
    task = dict(_conversation_value(state, "clarified_task") or {})
    if not task:
        return _fatal("missing_clarified_task", "缺少澄清任务配置")

    dispatch_mode = _resolve_chat_dispatch_mode()
    review_payload = interrupt(_build_review_payload(state=state, task=task, dispatch_mode=dispatch_mode))
    action_payload = review_payload if isinstance(review_payload, dict) else {"action": review_payload}
    action = str(action_payload.get("action") or "approve").strip().lower()

    if action in {"approve", "start", "execute"}:
        return {
            **_ok({"review_action": action}),
            "conversation": {
                "status": "ok",
                "review_state": "approved",
                "clarified_task": task,
            },
        }

    if action == "supplement":
        supplement = _normalize_resume_answer(action_payload) or _DEFAULT_CHAT_FALLBACK
        history = _history_from_state(_conversation_value(state, "chat_history"), initial_request)
        history.append(DialogueMessage(role="user", content=supplement))
        return {
            **_ok({"review_action": action}),
            "conversation": {
                "status": "ok",
                "review_state": "reclarify",
                "flow_state": "input_collected",
                "chat_history": _history_to_state(history),
                "clarified_task": None,
            },
        }

    if action == "override_task":
        try:
            override_task = _normalize_override_task(action_payload.get("task"))
        except Exception as exc:  # noqa: BLE001
            return _fatal("invalid_override_task", str(exc))
        return {
            **_ok({"review_action": action}),
            "conversation": {
                "status": "ok",
                "review_state": "approved",
                "clarified_task": override_task,
            },
        }

    if action == "cancel":
        return _fatal("chat_cancelled", "用户取消执行")

    return _fatal("invalid_review_action", f"不支持的 review action: {action}")



def chat_prepare_execution_handoff(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 进入 planning / multi-dispatch 前的参数交接节点。"""
    cli_args = dict(state.get("cli_args") or {})
    task = dict(_conversation_value(state, "clarified_task") or {})
    if not task:
        return _fatal("missing_clarified_task", "缺少澄清任务配置")

    dispatch_mode = _resolve_chat_dispatch_mode()
    # `clarified_task` 是 chat 阶段产物，这里只做进入 planning 的参数交接。
    base_params = _apply_serial_mode_overrides({
        "list_url": task.get("list_url", ""),
        "task_description": task.get("task_description", ""),
        "fields": [_field_to_dict(item) for item in task.get("fields", [])],
        "max_pages": _coalesce_cli_option(cli_args, "max_pages", task.get("max_pages")),
        "target_url_count": _coalesce_cli_option(
            cli_args,
            "target_url_count",
            task.get("target_url_count"),
        ),
        "consumer_concurrency": _coalesce_cli_option(
            cli_args,
            "consumer_concurrency",
            task.get("consumer_concurrency"),
        ),
        "field_explore_count": _coalesce_cli_option(
            cli_args,
            "field_explore_count",
            task.get("field_explore_count"),
        ),
        "field_validate_count": _coalesce_cli_option(
            cli_args,
            "field_validate_count",
            task.get("field_validate_count"),
        ),
        "pipeline_mode": cli_args.get("pipeline_mode"),
        "headless": cli_args["headless"] if "headless" in cli_args else None,
        "output_dir": str(cli_args.get("output_dir") or "output"),
        "serial_mode": cli_args.get("serial_mode"),
        "request": str(cli_args.get("request") or task.get("task_description") or ""),
        "max_concurrent": _coalesce_cli_option(cli_args, "max_concurrent", None),
        "execution_mode_resolved": dispatch_mode,
        "runtime_subtask_max_children": cli_args.get("runtime_subtask_max_children"),
        "runtime_subtasks_use_main_model": cli_args.get("runtime_subtasks_use_main_model"),
        "selected_skills": list(_conversation_value(state, "selected_skills") or []),
        "global_browser_budget": cli_args.get("global_browser_budget"),
    })
    concurrency = resolve_concurrency_settings(base_params)
    normalized = dict(base_params)
    normalized["consumer_concurrency"] = concurrency.consumer_concurrency
    normalized["max_concurrent"] = concurrency.max_concurrent
    normalized["global_browser_budget"] = concurrency.global_browser_budget

    return {
        **_ok({"execution_mode_resolved": "multi"}),
        "normalized_params": normalized,
        "conversation": {"status": "ok", "normalized_params": normalized},
    }


# ---------------------------------------------------------------------------
# 历史任务智能复用
# ---------------------------------------------------------------------------


def _parse_user_choice(answer: Any) -> int:
    """从用户的回答中提取选项序号。"""
    if isinstance(answer, int):
        return answer
    if isinstance(answer, dict):
        raw = answer.get("choice") or answer.get("index") or answer.get("action")
    else:
        raw = answer
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return -1


async def _llm_rank_history(
    current_desc: str,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """用 LLM 从历史任务中筛选并排序最多 3 个与当前意图最相关的候选。

    Returns:
        按相关性从高到低排列的历史任务列表（最多 3 个），
        如果都不相关则返回空列表。
    """
    # 构建候选列表文本
    lines: list[str] = []
    for i, h in enumerate(history):
        fields = h.get("fields") or []
        fields_text = ", ".join(fields) if fields else "未知"
        count = h.get("collected_count", 0)
        desc = h.get("task_description", "")
        lines.append(f"{i + 1}. [{desc}] (采集字段: {fields_text}，已采集 {count} 条)")
    candidates_text = "\n".join(lines)

    prompt = (
        "你是一个任务意图匹配助手。\n\n"
        f"当前用户的新任务描述：[{current_desc}]\n\n"
        f"该网站下曾经执行过的历史任务：\n{candidates_text}\n\n"
        "请从历史任务中选出与当前任务**采集意图最相关**的，最多选 3 个。\n"
        "按相关性从高到低排列，返回它们的序号列表。\n\n"
        "判断标准：\n"
        '- "采集新闻" 和 "帮我抓取新闻"是相关的（同义表达）\n'
        '- "采集新闻标题" 和 "采集新闻正文" 是不同的任务（字段不同）\n'
        "- 如果都不相关，返回空列表\n\n"
        '返回格式（严格 JSON）：\n{"ranked": [序号1, 序号2, ...]}\n'
        '例如：{"ranked": [2, 1]} 或 {"ranked": []}'
    )

    api_key = config.llm.planner_api_key or config.llm.api_key
    api_base = config.llm.planner_api_base or config.llm.api_base
    model = config.llm.planner_model or config.llm.model

    llm = ChatOpenAI(
        api_key=api_key,
        base_url=api_base,
        model=model,
        temperature=0.0,
        max_tokens=256,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    try:
        response = await ainvoke_with_stream(llm, [HumanMessage(content=prompt)])
        parsed = extract_json_dict_from_llm_payload(response)
    except Exception as exc:
        logger.warning("[HistoryMatch] LLM 排序历史任务失败: %s", exc)
        return []

    ranked_indices = list(parsed.get("ranked", [])) if parsed else []

    # 校验并映射回历史任务对象
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for idx in ranked_indices:
        try:
            index = int(idx)
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(history) or index in seen:
            continue
        seen.add(index)
        selected.append(history[index - 1])
        if len(selected) >= _MAX_HISTORY_CANDIDATES:
            break

    return selected


async def chat_history_match(state: dict[str, Any]) -> dict[str, Any]:
    """在澄清完成后、执行确认前，检查是否可以复用历史任务。

    LLM 从历史任务中筛选最多 3 个最相关的候选，
    加上"创建新任务"组成最多 4 个选项，interrupt 让用户选择。
    如果用户已在本轮对话中完成过选择（补充需求重新生成场景），则直接跳过。
    """
    task = dict(_conversation_value(state, "clarified_task") or {})
    signature_payload = {
        "list_url": str(task.get("list_url") or ""),
        "task_description": str(task.get("task_description") or ""),
        "fields": [_field_to_dict(item) for item in list(task.get("fields") or [])],
    }
    task_signature = hashlib.sha1(str(signature_payload).encode("utf-8")).hexdigest()
    # 已经选择过且输入签名未变化，跳过重复匹配
    if state.get("history_match_done") and str(state.get("history_match_signature") or "") == task_signature:
        return _ok({"history_reused": False, "skipped": True})
    list_url = str(task.get("list_url") or "")
    current_desc = str(task.get("task_description") or "")

    if not list_url:
        return {**_ok(), "history_match_done": True}

    # 1. 查找历史任务
    cli_args = dict(state.get("cli_args") or {})
    output_dir = str(cli_args.get("output_dir") or "output")
    registry = TaskRunQueryService()
    history = registry.find_by_url(list_url)

    if not history:
        return {**_ok(), "history_match_done": True}

    # 2. 调用 LLM 筛选最多 3 个最相关的候选
    candidates = await _llm_rank_history(current_desc, history)

    if not candidates:
        return {**_ok(), "history_match_done": True}

    # 3. 构建选项列表：最多 3 个历史 + 1 个新任务
    options: list[dict[str, Any]] = []
    for i, candidate in enumerate(candidates[:_MAX_HISTORY_CANDIDATES], start=1):
        options.append({
            "index": i,
            "type": "history",
            "label": (
                f"复用历史任务：「{candidate['task_description']}」"
                f"（已采集 {candidate.get('collected_count', 0)} 条）"
            ),
            "registry_id": candidate.get("registry_id", ""),
            "task_description": candidate["task_description"],
        })
    options.append({
        "index": len(options) + 1,
        "type": "new",
        "label": f"创建新任务：「{current_desc}」",
    })

    # 4. interrupt 让用户选择
    answer = interrupt({
        "type": "history_task_select",
        "thread_id": str(state.get("thread_id") or ""),
        "message": "检测到该网站下有历史采集任务，请选择：",
        "options": options,
    })

    # 5. 解析用户选择
    choice = _parse_user_choice(answer)

    selected = None
    for opt in options:
        if opt["index"] == choice and opt["type"] == "history":
            selected = opt
            break

    if selected:
        # 保留用户原始描述，用历史描述覆盖以命中缓存/进度
        task["original_task_description"] = task.get("task_description", "")
        task["task_description"] = selected["task_description"]
        logger.info(
            "[HistoryMatch] 用户选择复用历史任务: %s (原始意图: %s)",
            selected["task_description"][:60],
            task["original_task_description"][:60],
        )
        return {
            **_ok({"history_reused": True, "matched_registry_id": selected["registry_id"]}),
            "conversation": {"status": "ok", "clarified_task": task},
            "history_match_done": True,
            "history_match_signature": task_signature,
        }

    logger.info("[HistoryMatch] 用户选择创建新任务")
    return {
        **_ok({"history_reused": False}),
        "history_match_done": True,
        "history_match_signature": task_signature,
    }

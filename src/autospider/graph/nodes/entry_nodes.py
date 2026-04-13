"""入口与参数归一化节点。"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from ...common.config import config
from ...common.experience import SkillRuntime
from ...common.grouping_semantics import normalize_grouping_semantics
from ...common.llm import TaskClarifier
from ...common.llm.streaming import ainvoke_with_stream
from ...common.llm.trace_logger import append_llm_trace
from ...common.logger import get_logger
from ...common.protocol import (
    extract_json_dict_from_llm_payload,
    extract_response_text_from_llm_payload,
    summarize_llm_payload,
)
from ...common.storage.task_run_query_service import TaskRunQueryService
from ...domain.chat import ClarifiedTask, DialogueMessage
from ...domain.fields import FieldDefinition
from ...pipeline.helpers import resolve_semantic_identity
from ...common.validators import validate_task_description, validate_url
from ...graph.execution_handoff import build_chat_execution_params, build_chat_review_payload

logger = get_logger(__name__)


def _meta_value(state: dict[str, Any], key: str, default: Any = None) -> Any:
    meta = dict(state.get("meta") or {})
    return meta.get(key, state.get(key, default))


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
        "group_by": task.group_by,
        "per_group_target_count": task.per_group_target_count,
        "total_target_count": task.total_target_count,
        "category_discovery_mode": task.category_discovery_mode,
        "requested_categories": list(task.requested_categories),
        "category_examples": list(task.category_examples),
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


def _ensure_runtime_payload_slots(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params or {})
    normalized.setdefault("decision_context", {})
    normalized.setdefault("world_snapshot", {})
    normalized.setdefault("control_snapshot", {})
    normalized.setdefault("failure_records", [])
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

    grouping = normalize_grouping_semantics(raw_task)
    return {
        "intent": str(raw_task.get("intent") or "").strip(),
        "list_url": validate_url(str(raw_task.get("list_url") or "")),
        "task_description": validate_task_description(str(raw_task.get("task_description") or "")),
        "fields": normalized_fields,
        **grouping,
        "max_pages": raw_task.get("max_pages"),
        "target_url_count": raw_task.get("target_url_count"),
        "consumer_concurrency": raw_task.get("consumer_concurrency"),
        "field_explore_count": raw_task.get("field_explore_count"),
        "field_validate_count": raw_task.get("field_validate_count"),
    }



def route_entry(state: dict[str, Any]) -> dict[str, Any]:
    """入口路由节点。"""
    mode = _meta_value(state, "entry_mode")
    if not mode:
        return _fatal("missing_entry_mode", "缺少 entry_mode")
    if str(mode) != "chat_pipeline":
        return _fatal("invalid_entry_mode", f"不支持的 entry_mode: {mode}")
    return {
        **_ok({"entry_mode": mode}),
        "normalized_params": apply_serial_mode_overrides(dict(state.get("cli_args") or {})),
    }



def normalize_pipeline_params(state: dict[str, Any]) -> dict[str, Any]:
    """执行参数归一化。"""
    normalized = _ensure_runtime_payload_slots(
        _apply_serial_mode_overrides(dict(state.get("cli_args") or {}))
    )
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
            "thread_id": str(_meta_value(state, "thread_id") or ""),
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
    review_payload = interrupt(
        build_chat_review_payload(state=state, task=task, dispatch_mode=dispatch_mode)
    )
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
    task = dict(_conversation_value(state, "clarified_task") or {})
    if not task:
        return _fatal("missing_clarified_task", "缺少澄清任务配置")
    list_url = str(task.get("list_url") or "").strip()
    if not list_url:
        return _fatal("missing_list_url", "澄清任务缺少列表页 URL")
    try:
        validate_url(list_url)
    except Exception:
        return _fatal("invalid_list_url", "澄清任务的列表页 URL 非法")

    dispatch_mode = _resolve_chat_dispatch_mode()
    normalized = build_chat_execution_params(
        state=state,
        task=task,
        dispatch_mode=dispatch_mode,
    )

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


def _llm_model_name(llm: Any) -> str | None:
    return getattr(llm, "model_name", None) or getattr(llm, "model", None) or config.llm.model


def _current_semantic_identity(task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return resolve_semantic_identity(task)


async def _llm_rank_history(
    current_desc: str,
    current_semantic_signature: str,
    current_strategy_payload: dict[str, Any],
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
        semantic_signature = str(h.get("semantic_signature") or "")
        strategy_payload = json.dumps(
            dict(h.get("strategy_payload") or {}),
            ensure_ascii=False,
            sort_keys=True,
        )
        lines.append(
            f"{i + 1}. [{desc}] "
            f"(采集字段: {fields_text}，已采集 {count} 条，"
            f"semantic_signature: {semantic_signature or '无'}，"
            f"strategy_payload: {strategy_payload})"
        )
    candidates_text = "\n".join(lines)
    current_strategy_text = json.dumps(current_strategy_payload, ensure_ascii=False, sort_keys=True)

    prompt = (
        "你是一个任务意图匹配助手。\n\n"
        f"当前用户的新任务描述：[{current_desc}]\n\n"
        f"当前任务的语义身份：semantic_signature={current_semantic_signature}，"
        f"strategy_payload={current_strategy_text}\n\n"
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
        raw_response = extract_response_text_from_llm_payload(response)
        response_summary = summarize_llm_payload(response)
        parsed = extract_json_dict_from_llm_payload(response)
        ranked_indices = list(parsed.get("ranked", [])) if parsed else []
        append_llm_trace(
            component="entry_history_match_ranker",
            payload={
                "model": _llm_model_name(llm),
                "input": {
                    "current_desc": current_desc,
                    "history_candidates": history,
                    "prompt": prompt,
                },
                "output": {
                    "raw_response": raw_response,
                    "parsed_payload": parsed,
                    "ranked_indices": ranked_indices,
                },
                "response_summary": response_summary,
            },
        )
    except Exception as exc:
        append_llm_trace(
            component="entry_history_match_ranker",
            payload={
                "model": _llm_model_name(llm),
                "input": {
                    "current_desc": current_desc,
                    "history_candidates": history,
                    "prompt": prompt,
                },
                "output": {
                    "raw_response": "",
                    "parsed_payload": None,
                    "ranked_indices": [],
                },
                "response_summary": {},
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            },
        )
        logger.warning("[HistoryMatch] LLM 排序历史任务失败: %s", exc)
        return []

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
    semantic_signature, strategy_payload = _current_semantic_identity(task)
    signature_payload = {
        "list_url": str(task.get("list_url") or ""),
        "semantic_signature": semantic_signature,
        "strategy_payload": strategy_payload,
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
    registry = TaskRunQueryService()
    history = registry.find_by_url(list_url)

    if not history:
        return {**_ok(), "history_match_done": True}

    # 2. 调用 LLM 筛选最多 3 个最相关的候选
    candidates = await _llm_rank_history(
        current_desc,
        semantic_signature,
        strategy_payload,
        history,
    )

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
            "semantic_signature": str(candidate.get("semantic_signature") or ""),
            "strategy_payload": dict(candidate.get("strategy_payload") or {}),
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
        "thread_id": str(_meta_value(state, "thread_id") or ""),
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
        selected_strategy = dict(selected.get("strategy_payload") or {})
        task["matched_registry_id"] = selected["registry_id"]
        task["semantic_signature"] = str(selected.get("semantic_signature") or semantic_signature)
        task["strategy_payload"] = selected_strategy
        if selected_strategy:
            task.update(selected_strategy)
        logger.info(
            "[HistoryMatch] 用户选择复用历史任务: %s (当前意图保持: %s)",
            selected["task_description"][:60],
            str(task.get("task_description") or "")[:60],
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

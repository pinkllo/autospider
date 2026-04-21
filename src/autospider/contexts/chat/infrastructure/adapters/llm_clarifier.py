from __future__ import annotations

from typing import Any

from autospider.platform.llm.task_clarifier import TaskClarifier
from autospider.platform.shared_kernel.validators import validate_url
from autospider.contexts.chat.domain.model import (
    ClarificationResult,
    ClarifiedTask,
    DialogueMessage,
    RequestedField,
)

_DEFAULT_CLARIFICATION_QUESTION = "请补充你要采集的网站列表页 URL，以及你最关心的字段。"
_DEFAULT_READY_FALLBACK_QUESTION = "我还缺少可执行信息。请提供列表页 URL，并确认希望提取的字段。"
_DEFAULT_REJECT_REASON = "该需求暂时无法安全执行。"
_FALLBACK_QUESTION = (
    "我不会因为缺少 URL 直接拒绝任务。请在以下两种方式中二选一：\n"
    "A. 直接提供目标站的列表页 URL；\n"
    "B. 从搜索引擎起步（例如 https://www.baidu.com ），由系统先搜索再进入目标站。\n"
    "如果页面需要登录，系统支持人工登录接管后继续执行。\n"
    "请回复 A 或 B；若选 B，请同时提供搜索关键词。"
)
_HARD_REJECT_KEYWORDS = (
    "违法",
    "非法",
    "攻击",
    "入侵",
    "破解",
    "盗号",
    "敏感隐私",
    "个人隐私",
    "恶意",
    "诈骗",
    "violence",
    "exploit",
    "hack",
    "phishing",
    "malware",
)


def _to_history_payload(history: list[DialogueMessage]) -> list[dict[str, str]]:
    return [message.to_payload() for message in history]


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_positive_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        resolved = int(value)
    except (TypeError, ValueError):
        return None
    return resolved if resolved > 0 else None


def _parse_fields(value: Any) -> tuple[RequestedField, ...]:
    if not isinstance(value, list):
        return ()
    fields: list[RequestedField] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        field = RequestedField.from_mapping(item)
        if field.name and field.description:
            fields.append(field)
    return tuple(fields)


def _build_task(payload: dict[str, Any]) -> ClarifiedTask | None:
    list_url = str(payload.get("list_url") or "").strip()
    task_description = str(payload.get("task_description") or "").strip()
    fields = _parse_fields(payload.get("fields"))
    if not list_url or not task_description or not fields:
        return None
    try:
        validated_url = validate_url(list_url)
    except Exception:
        return None
    return ClarifiedTask(
        intent=str(payload.get("intent") or "").strip(),
        list_url=validated_url,
        task_description=task_description,
        fields=fields,
        group_by=str(payload.get("group_by") or "none").strip() or "none",
        per_group_target_count=_to_positive_int(payload.get("per_group_target_count")),
        total_target_count=_to_positive_int(payload.get("total_target_count")),
        category_discovery_mode=str(payload.get("category_discovery_mode") or "auto").strip()
        or "auto",
        requested_categories=tuple(str(item).strip() for item in list(payload.get("requested_categories") or [])),
        category_examples=tuple(str(item).strip() for item in list(payload.get("category_examples") or [])),
        max_pages=_to_positive_int(payload.get("max_pages")),
        target_url_count=_to_positive_int(payload.get("target_url_count")),
        consumer_concurrency=_to_positive_int(payload.get("consumer_concurrency")),
        field_explore_count=_to_positive_int(payload.get("field_explore_count")),
        field_validate_count=_to_positive_int(payload.get("field_validate_count")),
    )


def _is_hard_reject(reason: str, history: list[DialogueMessage]) -> bool:
    haystack = " ".join([reason, *[message.content for message in history[-10:]]]).lower()
    return any(keyword in haystack for keyword in _HARD_REJECT_KEYWORDS)


def _result_from_payload(
    payload: dict[str, Any],
    history: list[DialogueMessage],
) -> ClarificationResult:
    status = str(payload.get("status") or "need_clarification").strip().lower()
    if status not in {"need_clarification", "ready", "reject"}:
        status = "need_clarification"
    intent = str(payload.get("intent") or "").strip()
    confidence = _to_float(payload.get("confidence"), 0.0)
    next_question = str(payload.get("next_question") or "").strip()
    reason = str(payload.get("rejection_reason") or "").strip()
    task = None
    if status == "ready":
        task = _build_task(payload)
        if task is None:
            status = "need_clarification"
            next_question = next_question or _DEFAULT_READY_FALLBACK_QUESTION
    if status == "reject" and not _is_hard_reject(reason, history):
        status = "need_clarification"
        reason = ""
        if not next_question:
            next_question = _FALLBACK_QUESTION
    if status == "need_clarification" and not next_question:
        next_question = _DEFAULT_CLARIFICATION_QUESTION
    if status == "reject" and not reason:
        reason = _DEFAULT_REJECT_REASON
    return ClarificationResult(
        status=status,
        intent=intent,
        confidence=confidence,
        next_question=next_question,
        reason=reason,
        task=task,
    )


class TaskClarifierAdapter:
    def __init__(self, clarifier: TaskClarifier | None = None) -> None:
        self._clarifier = clarifier or TaskClarifier()

    @property
    def llm(self):  # type: ignore[no-untyped-def]
        return self._clarifier.llm

    async def clarify(
        self,
        history: list[DialogueMessage],
        *,
        available_skills: list[dict[str, str]] | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        selected_skills_context: str | None = None,
    ) -> ClarificationResult:
        payload = await self._clarifier.clarify(
            _to_history_payload(history),
            available_skills=available_skills,
            selected_skills=selected_skills,
            selected_skills_context=selected_skills_context,
        )
        return _result_from_payload(payload, history)

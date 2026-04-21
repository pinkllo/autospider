"""LLM 协议消息到 Action 的归一化。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from autospider.platform.llm.protocol import parse_protocol_message_diagnostics
from autospider.platform.shared_kernel.types import Action, ActionType

CONTRACT_VIOLATION_CATEGORY = "contract_violation"
INVALID_PROTOCOL_DETAIL = "invalid_protocol_message"


def build_contract_violation_failure_record(
    *,
    component: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    return {
        "page_id": "",
        "category": CONTRACT_VIOLATION_CATEGORY,
        "detail": INVALID_PROTOCOL_DETAIL,
        "metadata": {
            "component": str(component or ""),
            "action": str(payload.get("action") or ""),
            "response_text": str(payload.get("response_text") or ""),
            "raw_payload": payload.get("raw_payload"),
            "validation_errors": [str(item) for item in list(payload.get("validation_errors") or [])],
        },
    }


def _resolve_scroll_delta(args: Mapping[str, Any]) -> tuple[int, int] | None:
    scroll_delta = args.get("scroll_delta")
    if isinstance(scroll_delta, list) and len(scroll_delta) == 2:
        return (int(scroll_delta[0]), int(scroll_delta[1]))
    return None


def _resolve_timeout_ms(args: Mapping[str, Any]) -> int:
    try:
        return int(args.get("timeout_ms") or 5000)
    except (TypeError, ValueError):
        return 5000


def build_action_from_protocol_message(message: Mapping[str, Any]) -> Action:
    action_name = str(message.get("action") or "").strip().lower()
    args = message.get("args")
    normalized_args = dict(args) if isinstance(args, Mapping) else {}
    thinking = str(message.get("thinking") or "").strip()
    try:
        action_type = ActionType(action_name)
    except ValueError:
        fallback_thinking = thinking or "LLM 输出未包含可执行 action，已进入重试"
        return Action(action=ActionType.RETRY, thinking=fallback_thinking)
    return Action(
        action=action_type,
        mark_id=normalized_args.get("mark_id"),
        target_text=normalized_args.get("target_text"),
        text=normalized_args.get("text"),
        key=normalized_args.get("key"),
        url=normalized_args.get("url"),
        scroll_delta=_resolve_scroll_delta(normalized_args),
        timeout_ms=_resolve_timeout_ms(normalized_args),
        thinking=thinking,
        expectation=normalized_args.get("expectation") or normalized_args.get("summary"),
        summary=normalized_args.get("summary"),
    )


def build_protocol_failure_action(
    *,
    component: str,
    diagnostics: dict[str, Any],
    response_preview: str,
) -> Action:
    failure_record = build_contract_violation_failure_record(
        component=component,
        diagnostics=diagnostics,
    )
    errors = list(failure_record["metadata"].get("validation_errors") or [])
    error_summary = "; ".join(errors[:2]) or response_preview[:200]
    return Action(
        action=ActionType.RETRY,
        thinking=f"contract_violation: {error_summary}",
        summary="contract_violation",
        failure_record=failure_record,
    )


def parse_action_from_response(
    *,
    component: str,
    response_payload: Any,
) -> Action:
    diagnostics = parse_protocol_message_diagnostics(response_payload)
    message = diagnostics.get("message")
    if isinstance(message, Mapping):
        return build_action_from_protocol_message(message)
    response_preview = str(getattr(response_payload, "content", response_payload))
    return build_protocol_failure_action(
        component=component,
        diagnostics=diagnostics,
        response_preview=response_preview,
    )

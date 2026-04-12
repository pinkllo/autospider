"""Failure classification helpers for graph runtime and contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

TRANSIENT_CATEGORY = "transient"
CONTRACT_VIOLATION_CATEGORY = "contract_violation"
STATE_MISMATCH_CATEGORY = "state_mismatch"
SITE_DEFENSE_CATEGORY = "site_defense"
RULE_STALE_CATEGORY = "rule_stale"
FATAL_CATEGORY = "fatal"

INVALID_PROTOCOL_DETAIL = "invalid_protocol_message"

_TIMEOUT_HINTS = ("timeout", "timed out", "超时")
_STATE_MISMATCH_HINTS = ("state mismatch", "dom changed", "element detached")
_RULE_STALE_HINTS = ("rule stale", "selector stale", "xpath stale", "规则失效")
_SITE_DEFENSE_HINTS = (
    "captcha",
    "challenge",
    "too many requests",
    "429",
    "access denied",
    "forbidden",
    "bot detected",
)
_FATAL_HINTS = ("fatal", "schema corrupted", "invalid schema", "unsupported")
UNKNOWN_EXCEPTION_REASON = "unknown_exception"


def _snake_case(name: str) -> str:
    normalized = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
    return normalized.strip().lower()


def build_failure_record(
    *,
    category: str,
    detail: str,
    component: str,
    page_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload["component"] = str(component or "")
    return {
        "page_id": str(page_id or ""),
        "category": str(category or ""),
        "detail": str(detail or ""),
        "metadata": payload,
    }


def _exception_name(error: BaseException) -> str:
    return _snake_case(type(error).__name__)


def _exception_message(error: BaseException) -> str:
    return str(error or "").strip().lower()


def _has_hint(value: str, hints: tuple[str, ...]) -> bool:
    return any(hint in value for hint in hints)


def _is_timeout_error(error: BaseException) -> bool:
    return isinstance(error, TimeoutError) or _has_hint(
        f"{_exception_name(error)} {_exception_message(error)}",
        _TIMEOUT_HINTS,
    )


def _is_state_mismatch_error(error: BaseException) -> bool:
    name = _exception_name(error)
    return "state_mismatch" in name or _has_hint(_exception_message(error), _STATE_MISMATCH_HINTS)


def _is_rule_stale_error(error: BaseException) -> bool:
    name = _exception_name(error)
    return "rule_stale" in name or _has_hint(_exception_message(error), _RULE_STALE_HINTS)


def _is_site_defense_error(error: BaseException) -> bool:
    name = _exception_name(error)
    return "site_defense" in name or _has_hint(_exception_message(error), _SITE_DEFENSE_HINTS)


def _is_fatal_error(error: BaseException) -> bool:
    name = _exception_name(error)
    return "fatal" in name or _has_hint(_exception_message(error), _FATAL_HINTS)


def _classify_exception_category(error: BaseException) -> tuple[str, str]:
    if _is_timeout_error(error):
        return TRANSIENT_CATEGORY, "timeout"
    if _is_state_mismatch_error(error):
        return STATE_MISMATCH_CATEGORY, "state_mismatch"
    if _is_rule_stale_error(error):
        return RULE_STALE_CATEGORY, "rule_stale"
    if _is_site_defense_error(error):
        return SITE_DEFENSE_CATEGORY, "site_defense"
    if _is_fatal_error(error):
        return FATAL_CATEGORY, "fatal"
    return FATAL_CATEGORY, UNKNOWN_EXCEPTION_REASON


def classify_protocol_violation(
    *,
    component: str,
    diagnostics: Mapping[str, Any] | None,
    page_id: str = "",
) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    metadata = {
        "action": str(payload.get("action") or ""),
        "response_text": str(payload.get("response_text") or ""),
        "raw_payload": payload.get("raw_payload"),
        "validation_errors": [str(item) for item in list(payload.get("validation_errors") or [])],
    }
    return build_failure_record(
        category=CONTRACT_VIOLATION_CATEGORY,
        detail=INVALID_PROTOCOL_DETAIL,
        component=component,
        page_id=page_id,
        metadata=metadata,
    )


def classify_runtime_exception(
    *,
    component: str,
    error: BaseException,
    page_id: str = "",
) -> dict[str, Any]:
    category, classification_reason = _classify_exception_category(error)
    metadata = {
        "exception_type": type(error).__name__,
        "message": str(error),
        "classification_reason": classification_reason,
    }
    return build_failure_record(
        category=category,
        detail=_exception_name(error),
        component=component,
        page_id=page_id,
        metadata=metadata,
    )

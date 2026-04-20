from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from autospider.contexts.planning.domain.model import PlanJournalEntry, TaskPlan

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
_SITE_DEFENSE_HINTS = ("captcha", "challenge", "429", "access denied", "forbidden", "bot detected")
_FATAL_HINTS = ("fatal", "schema corrupted", "invalid schema", "unsupported")
UNKNOWN_EXCEPTION_REASON = "unknown_exception"


def _snake_case(name: str) -> str:
    normalized = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
    return normalized.strip().lower()


def _message(error: BaseException) -> str:
    return str(error or "").strip().lower()


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


def _matches(error: BaseException, hints: tuple[str, ...]) -> bool:
    payload = f"{_snake_case(type(error).__name__)} {_message(error)}"
    return any(hint in payload for hint in hints)


def _classify_exception_category(error: BaseException) -> tuple[str, str]:
    if isinstance(error, TimeoutError) or _matches(error, _TIMEOUT_HINTS):
        return TRANSIENT_CATEGORY, "timeout"
    if _matches(error, _STATE_MISMATCH_HINTS):
        return STATE_MISMATCH_CATEGORY, "state_mismatch"
    if _matches(error, _RULE_STALE_HINTS):
        return RULE_STALE_CATEGORY, "rule_stale"
    if _matches(error, _SITE_DEFENSE_HINTS):
        return SITE_DEFENSE_CATEGORY, "site_defense"
    if _matches(error, _FATAL_HINTS):
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
    category, reason = _classify_exception_category(error)
    return build_failure_record(
        category=category,
        detail=_snake_case(type(error).__name__),
        component=component,
        page_id=page_id,
        metadata={
            "exception_type": type(error).__name__,
            "message": str(error),
            "classification_reason": reason,
        },
    )


class FailureClassifier:
    def classify_runtime_exception(self, *, component: str, error: BaseException) -> dict[str, Any]:
        payload = classify_runtime_exception(component=component, error=error)
        payload.pop("page_id", None)
        return payload

    def classify_protocol_violation(
        self, *, component: str, diagnostics: dict[str, Any] | None
    ) -> dict[str, Any]:
        payload = classify_protocol_violation(component=component, diagnostics=diagnostics)
        payload.pop("page_id", None)
        return payload


class ReplanStrategy:
    def apply(
        self,
        *,
        plan: TaskPlan,
        reason: str,
        failed_subtask_id: str | None = None,
    ) -> TaskPlan:
        journal = list(plan.journal)
        journal.append(
            PlanJournalEntry(
                entry_id=f"replan-{len(journal) + 1}",
                node_id=failed_subtask_id,
                phase="planning",
                action="replan",
                reason=reason,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        return plan.model_copy(
            update={
                "journal": journal,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

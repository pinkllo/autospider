"""Recovery directives derived from classified failures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...contexts.planning.domain import (
    CONTRACT_VIOLATION_CATEGORY,
    FATAL_CATEGORY,
    RULE_STALE_CATEGORY,
    SITE_DEFENSE_CATEGORY,
    STATE_MISMATCH_CATEGORY,
    TRANSIENT_CATEGORY,
)

RETRY_ACTION = "retry"
REASK_ACTION = "reask"
REPLAN_ACTION = "replan"
HUMAN_INTERVENTION_ACTION = "human_intervention"
FAIL_ACTION = "fail"

RETRY_DELAYS = (1.0, 2.0)
_CATEGORY_TO_ACTION = {
    TRANSIENT_CATEGORY: RETRY_ACTION,
    CONTRACT_VIOLATION_CATEGORY: REASK_ACTION,
    STATE_MISMATCH_CATEGORY: REPLAN_ACTION,
    RULE_STALE_CATEGORY: REPLAN_ACTION,
    SITE_DEFENSE_CATEGORY: HUMAN_INTERVENTION_ACTION,
    FATAL_CATEGORY: FAIL_ACTION,
}
UNKNOWN_FAILURE_CATEGORY_REASON = "unknown_failure_category"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    action: str
    delay_seconds: float = 0.0
    reason: str = ""


def _resolve_retry_delay(failure_count: int) -> float:
    if not RETRY_DELAYS:
        return 0.0
    bounded_index = min(max(failure_count, 0), len(RETRY_DELAYS) - 1)
    return float(RETRY_DELAYS[bounded_index])


def _resolve_category_action(category: str) -> tuple[str, str]:
    if category in _CATEGORY_TO_ACTION:
        return _CATEGORY_TO_ACTION[category], category
    return FAIL_ACTION, UNKNOWN_FAILURE_CATEGORY_REASON


def build_recovery_directive(
    *,
    failure_record: Mapping[str, Any] | None,
    failure_count: int,
    max_retries: int,
) -> RecoveryDecision:
    payload = dict(failure_record or {})
    category = str(payload.get("category") or "")
    action, reason = _resolve_category_action(category)
    retry_budget = max(int(max_retries or 0), 0)
    if action == RETRY_ACTION and failure_count >= retry_budget:
        return RecoveryDecision(action=FAIL_ACTION, reason="retry_budget_exhausted")
    if action != RETRY_ACTION:
        return RecoveryDecision(action=action, reason=reason)
    return RecoveryDecision(
        action=RETRY_ACTION,
        delay_seconds=_resolve_retry_delay(failure_count),
        reason=reason or "retryable_failure",
    )

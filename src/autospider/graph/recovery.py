"""Recovery directives derived from classified failures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .failures import CONTRACT_VIOLATION_CATEGORY

RETRY_DELAYS = (1.0, 2.0)


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


def build_recovery_directive(
    *,
    failure_record: Mapping[str, Any] | None,
    failure_count: int,
    max_retries: int,
) -> RecoveryDecision:
    payload = dict(failure_record or {})
    category = str(payload.get("category") or "")
    retry_budget = max(int(max_retries or 0), 0)
    if category == CONTRACT_VIOLATION_CATEGORY:
        return RecoveryDecision(action="fail", reason="contract_violation")
    if failure_count >= retry_budget:
        return RecoveryDecision(action="fail", reason="retry_budget_exhausted")
    return RecoveryDecision(
        action="retry",
        delay_seconds=_resolve_retry_delay(failure_count),
        reason="retryable_failure",
    )

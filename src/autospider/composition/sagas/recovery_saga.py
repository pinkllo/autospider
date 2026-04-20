from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from autospider.composition.graph.recovery import build_recovery_directive


@dataclass(frozen=True, slots=True)
class RecoveryResolution:
    action: str
    delay_seconds: float
    reason: str


class RecoverySaga:
    def decide(
        self,
        *,
        failure_record: Mapping[str, Any] | None,
        failure_count: int,
        max_retries: int,
    ) -> RecoveryResolution:
        decision = build_recovery_directive(
            failure_record=failure_record,
            failure_count=failure_count,
            max_retries=max_retries,
        )
        return RecoveryResolution(
            action=decision.action,
            delay_seconds=decision.delay_seconds,
            reason=decision.reason,
        )

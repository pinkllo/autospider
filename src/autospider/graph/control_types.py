"""Control-layer contracts for dispatch and recovery decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_DISPATCH_STRATEGY = "sequential"
DEFAULT_MAX_CONCURRENCY = 1
DEFAULT_MAX_RETRIES = 2
DEFAULT_ESCALATION_CATEGORIES = ("system_failure",)


@dataclass(frozen=True, slots=True)
class PlanSpec:
    goal: str = ""
    page_id: str = ""
    stage: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DispatchDecision:
    strategy: str = DEFAULT_DISPATCH_STRATEGY
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecoveryDirective:
    max_retries: int = DEFAULT_MAX_RETRIES
    fail_fast: bool = True
    escalation_categories: tuple[str, ...] = DEFAULT_ESCALATION_CATEGORIES
    reason: str = ""


def build_default_dispatch_policy() -> DispatchDecision:
    return DispatchDecision()


def build_default_recovery_policy() -> RecoveryDirective:
    return RecoveryDirective()

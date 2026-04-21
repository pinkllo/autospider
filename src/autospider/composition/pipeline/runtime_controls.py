"""Shared runtime controls for concurrency and browser budgeting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autospider.platform.config.runtime import config


@dataclass(frozen=True, slots=True)
class ResolvedConcurrency:
    consumer_concurrency: int
    max_concurrent: int
    global_browser_budget: int


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return resolved if resolved > 0 else default


def resolve_concurrency_settings(params: dict[str, Any] | None) -> ResolvedConcurrency:
    normalized = dict(params or {})
    serial_mode = bool(normalized.get("serial_mode"))
    consumer_default = int(config.pipeline.consumer_concurrency or 1)
    dispatch_default = int(config.planner.max_concurrent_subtasks or 1)
    consumer = _coerce_positive_int(normalized.get("consumer_concurrency"), consumer_default)
    dispatch = _coerce_positive_int(normalized.get("max_concurrent"), dispatch_default)
    budget_default = max(dispatch, consumer, 1)
    budget = _coerce_positive_int(normalized.get("global_browser_budget"), budget_default)
    if serial_mode:
        consumer = 1
        dispatch = 1
        budget = 1
    return ResolvedConcurrency(
        consumer_concurrency=consumer,
        max_concurrent=dispatch,
        global_browser_budget=max(1, budget),
    )

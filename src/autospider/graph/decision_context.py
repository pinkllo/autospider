"""Decision-context builders for planner and runtime contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .control_types import (
    DispatchDecision,
    RecoveryDirective,
    build_default_dispatch_policy,
    build_default_recovery_policy,
)
from .workflow_access import coerce_workflow_state
from .world_model import (
    FailureRecord,
    PageModel,
    SuccessCriteria,
    WorldModel,
    build_initial_world_model,
)

DEFAULT_FAILURE_WINDOW = 3


@dataclass(frozen=True, slots=True)
class DecisionContext:
    page_id: str
    page_model: PageModel
    recent_failures: tuple[FailureRecord, ...]
    success_criteria: SuccessCriteria
    dispatch_policy: DispatchDecision
    recovery_policy: RecoveryDirective
    world_snapshot: dict[str, Any] = field(default_factory=dict)


def _coerce_dispatch_policy(value: Any) -> DispatchDecision:
    if isinstance(value, DispatchDecision):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    return DispatchDecision(
        strategy=str(payload.get("strategy") or build_default_dispatch_policy().strategy),
        max_concurrency=int(payload.get("max_concurrency", build_default_dispatch_policy().max_concurrency) or 0),
        reason=str(payload.get("reason") or ""),
    )


def _coerce_recovery_policy(value: Any) -> RecoveryDirective:
    if isinstance(value, RecoveryDirective):
        return value
    default = build_default_recovery_policy()
    payload = dict(value) if isinstance(value, Mapping) else {}
    categories = payload.get("escalation_categories") or default.escalation_categories
    return RecoveryDirective(
        max_retries=int(payload.get("max_retries", default.max_retries) or 0),
        fail_fast=bool(payload.get("fail_fast", default.fail_fast)),
        escalation_categories=tuple(str(item) for item in categories),
        reason=str(payload.get("reason") or ""),
    )


def _coerce_world_model(workflow: Mapping[str, Any]) -> WorldModel:
    world = dict(workflow.get("world") or {})
    raw_world_model = world.get("world_model")
    if isinstance(raw_world_model, WorldModel):
        return raw_world_model
    if isinstance(raw_world_model, Mapping):
        return build_initial_world_model(
            request_params=world.get("request_params"),
            page_models=raw_world_model.get("page_models"),
            failure_records=raw_world_model.get("failure_records"),
            success_criteria=raw_world_model.get("success_criteria"),
        )
    return build_initial_world_model(
        request_params=world.get("request_params"),
        failure_records=world.get("failure_records"),
    )


def summarize_page_model(page_model: PageModel) -> dict[str, Any]:
    return {
        "page_id": page_model.page_id,
        "url": page_model.url,
        "page_type": page_model.page_type,
        "links": page_model.links,
        "depth": page_model.depth,
    }


def _summarize_failure_record(record: FailureRecord) -> dict[str, Any]:
    return {
        "page_id": record.page_id,
        "category": record.category,
        "detail": record.detail,
        "metadata": dict(record.metadata),
    }


def _coerce_failure_record(value: Any) -> FailureRecord:
    if isinstance(value, FailureRecord):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    return FailureRecord(
        page_id=str(payload.get("page_id") or ""),
        category=str(payload.get("category") or ""),
        detail=str(payload.get("detail") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def summarize_failures(
    failure_records: list[Any] | tuple[Any, ...],
    *,
    page_id: str | None = None,
    limit: int = DEFAULT_FAILURE_WINDOW,
) -> tuple[FailureRecord, ...]:
    selected: list[FailureRecord] = []
    for item in reversed(list(failure_records or [])):
        record = _coerce_failure_record(item)
        if page_id and record.page_id and record.page_id != page_id:
            continue
        selected.append(record)
        if len(selected) >= limit:
            break
    selected.reverse()
    return tuple(selected)


def build_decision_context(
    workflow: Mapping[str, Any] | None,
    *,
    page_id: str | None = None,
) -> DecisionContext:
    normalized_workflow = coerce_workflow_state(workflow)
    world_model = _coerce_world_model(normalized_workflow)
    world = dict(normalized_workflow.get("world") or {})
    control = dict(normalized_workflow.get("control") or {})
    resolved_page_id = str(page_id or next(iter(world_model.page_models), ""))
    page_model = world_model.page_models.get(resolved_page_id, PageModel(page_id=resolved_page_id))
    failure_source = world.get("failure_records") or world_model.failure_records
    recent_failures = summarize_failures(failure_source, page_id=resolved_page_id)
    success_criteria = world_model.success_criteria
    return DecisionContext(
        page_id=resolved_page_id,
        page_model=page_model,
        recent_failures=recent_failures,
        success_criteria=success_criteria,
        dispatch_policy=_coerce_dispatch_policy(control.get("dispatch_policy")),
        recovery_policy=_coerce_recovery_policy(control.get("recovery_policy")),
        world_snapshot={
            "page_model": summarize_page_model(page_model),
            "recent_failures": [_summarize_failure_record(record) for record in recent_failures],
            "success_criteria": {"target_url_count": success_criteria.target_url_count},
        },
    )

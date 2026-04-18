"""Decision-context builders for planner and runtime contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .control_types import (
    DispatchDecision,
    PlanSpec,
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

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


def _coerce_dispatch_policy(value: Any) -> DispatchDecision:
    if isinstance(value, DispatchDecision):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    default = build_default_dispatch_policy()
    return DispatchDecision(
        strategy=str(payload.get("strategy") or default.strategy),
        max_concurrency=int(payload.get("max_concurrency", default.max_concurrency) or 0),
        reason=str(payload.get("reason") or ""),
    )


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"invalid_bool: {value}")


def _coerce_recovery_policy(value: Any) -> RecoveryDirective:
    if isinstance(value, RecoveryDirective):
        return value
    default = build_default_recovery_policy()
    payload = dict(value) if isinstance(value, Mapping) else {}
    categories = payload.get("escalation_categories") or default.escalation_categories
    return RecoveryDirective(
        max_retries=int(payload.get("max_retries", default.max_retries) or 0),
        max_replans=int(payload.get("max_replans", default.max_replans) or 0),
        fail_fast=_parse_bool(payload.get("fail_fast"), default=default.fail_fast),
        escalation_categories=tuple(str(item) for item in categories),
        reason=str(payload.get("reason") or ""),
    )


def _resolve_request_params_source(
    *,
    raw_workflow: Mapping[str, Any] | None,
    raw_world_model: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    raw_world = dict(raw_workflow.get("world") or {}) if isinstance(raw_workflow, Mapping) else {}
    if "request_params" in raw_world:
        request_params = raw_world.get("request_params")
        return request_params if isinstance(request_params, Mapping) else None
    request_params = raw_world_model.get("request_params")
    if isinstance(request_params, Mapping):
        return request_params
    return _resolve_legacy_request_params(raw_workflow)


def _resolve_legacy_request_params(raw_workflow: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(raw_workflow, Mapping):
        return None
    conversation = raw_workflow.get("conversation")
    if isinstance(conversation, Mapping):
        params = conversation.get("normalized_params")
        if isinstance(params, Mapping):
            return params
    for key in ("normalized_params", "cli_args"):
        params = raw_workflow.get(key)
        if isinstance(params, Mapping):
            return params
    return None


def _coerce_world_model(
    workflow: Mapping[str, Any],
    *,
    raw_workflow: Mapping[str, Any] | None = None,
) -> WorldModel:
    world = dict(workflow.get("world") or {})
    raw_world_model = world.get("world_model")
    if isinstance(raw_world_model, WorldModel):
        return raw_world_model
    if isinstance(raw_world_model, Mapping):
        request_params = _resolve_request_params_source(
            raw_workflow=raw_workflow,
            raw_world_model=raw_world_model,
        )
        return build_initial_world_model(
            request_params=request_params,
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
        "metadata": dict(page_model.metadata),
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
    if limit <= 0:
        return ()
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


def _summarize_success_criteria(success_criteria: SuccessCriteria) -> dict[str, Any]:
    return {"target_url_count": success_criteria.target_url_count}


def _summarize_dispatch_policy(policy: DispatchDecision) -> dict[str, Any]:
    return {
        "strategy": policy.strategy,
        "max_concurrency": policy.max_concurrency,
        "reason": policy.reason,
    }


def _summarize_recovery_policy(policy: RecoveryDirective) -> dict[str, Any]:
    return {
        "max_retries": policy.max_retries,
        "max_replans": policy.max_replans,
        "fail_fast": policy.fail_fast,
        "escalation_categories": list(policy.escalation_categories),
        "reason": policy.reason,
    }


def _coerce_current_plan(value: Any) -> PlanSpec:
    if isinstance(value, PlanSpec):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    return PlanSpec(
        goal=str(payload.get("goal") or ""),
        page_id=str(payload.get("page_id") or ""),
        stage=str(payload.get("stage") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def _summarize_current_plan(current_plan: PlanSpec) -> dict[str, Any]:
    return {
        "goal": current_plan.goal,
        "page_id": current_plan.page_id,
        "stage": current_plan.stage,
        "metadata": dict(current_plan.metadata),
    }


def _select_failure_source(world: Mapping[str, Any], world_model: WorldModel) -> Any:
    if "failure_records" in world:
        return world.get("failure_records")
    return world_model.failure_records


def build_decision_context(
    workflow: Mapping[str, Any] | None,
    *,
    page_id: str | None = None,
) -> dict[str, Any]:
    normalized_workflow = coerce_workflow_state(workflow)
    world_model = _coerce_world_model(normalized_workflow, raw_workflow=workflow)
    world = dict(normalized_workflow.get("world") or {})
    control = dict(normalized_workflow.get("control") or {})
    current_plan = _coerce_current_plan(control.get("current_plan"))
    resolved_page_id = str(page_id or current_plan.page_id or next(iter(world_model.page_models), ""))
    page_model = world_model.page_models.get(resolved_page_id, PageModel(page_id=resolved_page_id))
    failure_source = _select_failure_source(world, world_model)
    recent_failures = summarize_failures(failure_source, page_id=resolved_page_id)
    success_criteria = world_model.success_criteria
    dispatch_policy = _coerce_dispatch_policy(control.get("dispatch_policy"))
    recovery_policy = _coerce_recovery_policy(control.get("recovery_policy"))
    return {
        "page_id": resolved_page_id,
        "page_model": summarize_page_model(page_model),
        "recent_failures": [_summarize_failure_record(record) for record in recent_failures],
        "success_criteria": _summarize_success_criteria(success_criteria),
        "current_plan": _summarize_current_plan(current_plan),
        "dispatch_policy": _summarize_dispatch_policy(dispatch_policy),
        "recovery_policy": _summarize_recovery_policy(recovery_policy),
    }

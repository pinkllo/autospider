"""Feedback control-layer nodes for dispatch monitoring and world updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..control_types import build_default_recovery_policy
from ..failures import (
    RULE_STALE_CATEGORY,
    STATE_MISMATCH_CATEGORY,
    build_failure_record,
    classify_runtime_exception,
)
from ..recovery import REPLAN_ACTION
from ..state_access import subtask_results as select_subtask_results
from ..state_access import request_params as select_request_params
from ..workflow_access import coerce_workflow_state
from ..world_model import build_initial_world_model, world_model_to_payload

AGGREGATE_ROUTE = "aggregate"
DISPATCH_AGGREGATE_REASON = "dispatch_ready_for_aggregation"
REPLAN_BUDGET_EXHAUSTED_REASON = "replan_budget_exhausted"
REPLAN_CATEGORIES = {RULE_STALE_CATEGORY, STATE_MISMATCH_CATEGORY}
FAILURE_STATUSES = {"system_failure", "business_failure"}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _world_state(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return _as_dict(state.get("world")) or _as_dict(workflow.get("world"))


def _control_state(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return _as_dict(state.get("control")) or _as_dict(workflow.get("control"))


def _feedback_failure_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    current_failures = _current_dispatch_failure_records(state)
    if current_failures:
        return current_failures
    world = _world_state(state)
    if "failure_records" in world:
        return [dict(item) for item in list(world.get("failure_records") or [])]
    params = select_request_params(state)
    return [dict(item) for item in list(params.get("failure_records") or [])]


def _subtask_result_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="python"))
    return {}


def _build_dispatch_failure_record(result: Any) -> dict[str, Any]:
    """Build a FailureRecord for a failed subtask.

    Prefers the typed ``failure_category`` emitted by the pipeline layer. Falls back
    to string-hint classification only when the pipeline did not (yet) surface a
    category — this keeps the control-plane decision stable against log-text rewording.
    """
    payload = _subtask_result_payload(result)
    status = str(payload.get("status") or "")
    if status not in FAILURE_STATUSES:
        return {}
    summary = _as_dict(payload.get("summary"))
    typed_category = str(summary.get("failure_category") or "").strip()
    typed_detail = str(summary.get("failure_detail") or "").strip()
    fallback_detail = str(summary.get("terminal_reason") or payload.get("error") or "").strip()
    detail = typed_detail or fallback_detail
    if not typed_category and not detail:
        return {}

    page_id = str(payload.get("subtask_id") or "")
    if typed_category:
        failure_record = build_failure_record(
            category=typed_category,
            detail=detail or typed_category,
            component="monitor_dispatch_node",
            page_id=page_id,
            metadata={
                "exception_type": "",
                "message": fallback_detail,
                "classification_reason": "pipeline_typed_signal",
            },
        )
    else:
        failure_record = classify_runtime_exception(
            component="monitor_dispatch_node",
            error=RuntimeError(fallback_detail),
            page_id=page_id,
        )

    metadata = dict(failure_record.get("metadata") or {})
    metadata["subtask_id"] = page_id
    metadata["subtask_status"] = status
    metadata["terminal_reason"] = str(summary.get("terminal_reason") or "")
    failure_record["metadata"] = metadata
    return failure_record


def _current_dispatch_failure_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    failure_records: list[dict[str, Any]] = []
    for item in select_subtask_results(state):
        failure_record = _build_dispatch_failure_record(item)
        if failure_record:
            failure_records.append(failure_record)
    return failure_records


def _resolve_feedback_strategy(
    failure_records: list[dict[str, Any]],
) -> tuple[str, str]:
    for item in failure_records:
        category = str(item.get("category") or "")
        if category in REPLAN_CATEGORIES:
            return REPLAN_ACTION, category
    return AGGREGATE_ROUTE, DISPATCH_AGGREGATE_REASON


def _normalize_world_model(
    *,
    world: dict[str, Any],
    request_params: dict[str, Any],
    failure_records: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_world_model = world.get("world_model")
    if isinstance(raw_world_model, Mapping):
        world_model = dict(raw_world_model)
    else:
        world_model = world_model_to_payload(
            build_initial_world_model(
                request_params=request_params,
                failure_records=failure_records,
            )
        )
    world_model["request_params"] = dict(request_params)
    world_model["failure_records"] = list(failure_records)
    return world_model


def _resolve_replan_budget(state: dict[str, Any], control: Mapping[str, Any]) -> int:
    """Resolve the max allowed replan cycles, honoring overrides in control / request_params."""
    default_max = build_default_recovery_policy().max_replans
    params = _as_dict(select_request_params(state))
    candidates = (
        _as_dict(control.get("recovery_policy")),
        _as_dict(params.get("recovery_policy")),
        _as_dict(_as_dict(params.get("decision_context")).get("recovery_policy")),
    )
    for payload in candidates:
        if "max_replans" in payload:
            try:
                return max(int(payload["max_replans"]), 0)
            except (TypeError, ValueError):
                continue
    return max(int(default_max or 0), 0)


def monitor_dispatch_node(state: dict[str, Any]) -> dict[str, Any]:
    control = dict(_control_state(state))
    world = dict(_world_state(state))
    failure_records = _feedback_failure_records(state)
    strategy_name, reason = _resolve_feedback_strategy(failure_records)
    previous_strategy = _as_dict(control.get("active_strategy"))
    prior_replan_count = int(previous_strategy.get("replan_count", 0) or 0)

    active_strategy: dict[str, Any] = {"name": strategy_name, "reason": reason}

    if strategy_name == REPLAN_ACTION:
        max_replans = _resolve_replan_budget(state, control)
        if prior_replan_count >= max_replans:
            # 预算耗尽：强制降级到 aggregate，结束 replan 回路，写入可观测 degradation。
            active_strategy = {
                "name": AGGREGATE_ROUTE,
                "reason": REPLAN_BUDGET_EXHAUSTED_REASON,
                "replan_count": prior_replan_count,
                "max_replans": max_replans,
                "degraded_from": REPLAN_ACTION,
                "replan_trigger_category": reason,
            }
        else:
            active_strategy["replan_count"] = prior_replan_count + 1
            active_strategy["max_replans"] = max_replans
    else:
        # 非 replan 决策透传已有 replan_count，供审计。
        if "replan_count" in previous_strategy:
            active_strategy["replan_count"] = prior_replan_count

    world["failure_records"] = list(failure_records)
    control["active_strategy"] = active_strategy
    return {
        "control": control,
        "world": world,
    }


def update_world_model_node(state: dict[str, Any]) -> dict[str, Any]:
    world = dict(_world_state(state))
    failure_records = _feedback_failure_records(state)
    request_params = dict(world.get("request_params") or select_request_params(state))
    request_params["failure_records"] = list(failure_records)
    world["request_params"] = dict(request_params)
    world["failure_records"] = list(failure_records)
    world["world_model"] = _normalize_world_model(
        world=world,
        request_params=request_params,
        failure_records=failure_records,
    )
    return {"world": world}

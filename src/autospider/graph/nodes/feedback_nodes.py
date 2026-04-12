"""Feedback control-layer nodes for dispatch monitoring and world updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..failures import RULE_STALE_CATEGORY, STATE_MISMATCH_CATEGORY
from ..recovery import REPLAN_ACTION
from ..state_access import request_params as select_request_params
from ..workflow_access import coerce_workflow_state
from ..world_model import build_initial_world_model, world_model_to_payload

AGGREGATE_ROUTE = "aggregate"
DISPATCH_AGGREGATE_REASON = "dispatch_ready_for_aggregation"
REPLAN_CATEGORIES = {RULE_STALE_CATEGORY, STATE_MISMATCH_CATEGORY}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _world_state(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return _as_dict(state.get("world")) or _as_dict(workflow.get("world"))


def _control_state(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return _as_dict(state.get("control")) or _as_dict(workflow.get("control"))


def _feedback_failure_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    feedback = _as_dict(state.get("feedback"))
    if "failure_records" in feedback:
        return [dict(item) for item in list(feedback.get("failure_records") or [])]
    world = _world_state(state)
    if "failure_records" in world:
        return [dict(item) for item in list(world.get("failure_records") or [])]
    params = select_request_params(state)
    return [dict(item) for item in list(params.get("failure_records") or [])]


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


def monitor_dispatch_node(state: dict[str, Any]) -> dict[str, Any]:
    control = dict(_control_state(state))
    failure_records = _feedback_failure_records(state)
    strategy_name, reason = _resolve_feedback_strategy(failure_records)
    control["active_strategy"] = {"name": strategy_name, "reason": reason}
    return {
        "control": control,
        "feedback": {"failure_records": failure_records, "route": strategy_name},
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

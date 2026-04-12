"""Planning control-layer nodes for main-graph orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..recovery import REPLAN_ACTION
from ..state_access import request_params as select_request_params
from ..workflow_access import coerce_workflow_state
from ..world_model import build_initial_world_model, world_model_to_payload

AGGREGATE_STRATEGY_NAME = "aggregate"
INITIAL_STRATEGY_REASON = "initial_dispatch_cycle"
REPLAN_STRATEGY_REASON = "feedback_requested_replan"
ALLOWED_ACTIVE_STRATEGIES = {AGGREGATE_STRATEGY_NAME, REPLAN_ACTION}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _world_state(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return _as_dict(state.get("world")) or _as_dict(workflow.get("world"))


def _control_state(state: dict[str, Any]) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return _as_dict(state.get("control")) or _as_dict(workflow.get("control"))


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


def initialize_world_model_node(state: dict[str, Any]) -> dict[str, Any]:
    world = dict(_world_state(state))
    request_params = dict(select_request_params(state))
    failure_records = [dict(item) for item in list(world.get("failure_records") or [])]
    world["request_params"] = dict(request_params)
    world["failure_records"] = list(failure_records)
    world["world_model"] = _normalize_world_model(
        world=world,
        request_params=request_params,
        failure_records=failure_records,
    )
    return {"world": world}


def plan_strategy_node(state: dict[str, Any]) -> dict[str, Any]:
    control = dict(_control_state(state))
    active_strategy = _as_dict(control.get("active_strategy"))
    strategy_name = str(active_strategy.get("name") or "")
    if not strategy_name:
        strategy_name = AGGREGATE_STRATEGY_NAME
    elif strategy_name not in ALLOWED_ACTIVE_STRATEGIES:
        raise ValueError(f"unknown_active_strategy: {strategy_name}")
    if strategy_name == REPLAN_ACTION:
        reason = str(active_strategy.get("reason") or REPLAN_STRATEGY_REASON)
    else:
        reason = str(active_strategy.get("reason") or INITIAL_STRATEGY_REASON)
    control["active_strategy"] = {"name": strategy_name, "reason": reason}
    return {"control": control}

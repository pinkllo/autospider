"""Workflow-shaped accessors and legacy adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .workflow_state import WorkflowState

DISPATCH_SUMMARY_KEYS = {
    "total",
    "completed",
    "no_data",
    "expanded",
    "business_failure",
    "system_failure",
    "failed",
    "skipped",
    "total_collected",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_error(value: Any) -> dict[str, str]:
    error = _as_dict(value)
    code = str(error.get("code") or "")
    message = str(error.get("message") or "")
    if not code and not message:
        return {}
    return {"code": code, "message": message}


def _legacy_request_params(state: dict[str, Any]) -> dict[str, Any]:
    conversation = _as_dict(state.get("conversation"))
    return (
        _as_dict(state.get("normalized_params"))
        or _as_dict(conversation.get("normalized_params"))
        or _as_dict(state.get("cli_args"))
    )


def _legacy_current_plan(state: dict[str, Any]) -> Any:
    dispatch = _as_dict(state.get("dispatch"))
    planning = _as_dict(state.get("planning"))
    dispatch_plan = dispatch.get("task_plan")
    if dispatch_plan is not None:
        return dispatch_plan
    root_plan = state.get("task_plan")
    if root_plan is not None:
        return root_plan
    planning_plan = planning.get("task_plan")
    if planning_plan is not None:
        return planning_plan
    return None


def _merge_mappings(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, Mapping):
            merged.update(dict(value))
    return merged


def _looks_like_dispatch_summary(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return any(key in value for key in DISPATCH_SUMMARY_KEYS)


def _legacy_dispatch_summary(state: dict[str, Any]) -> dict[str, Any]:
    dispatch = _as_dict(state.get("dispatch"))
    merged = _merge_mappings(
        state.get("dispatch_result"),
        dispatch.get("dispatch_result"),
        dispatch.get("summary"),
    )
    if merged:
        return merged
    root_summary = _as_dict(state.get("summary"))
    if _looks_like_dispatch_summary(root_summary):
        return root_summary
    return {}


def _legacy_final_error(state: dict[str, Any]) -> dict[str, str]:
    result = _as_dict(state.get("result"))
    root_error = _normalize_error(state.get("error"))
    node_error = _normalize_error(state.get("node_error"))
    coded_error = _normalize_error(
        {
            "code": state.get("error_code"),
            "message": state.get("error_message"),
        }
    )
    return (
        _normalize_error(result.get("final_error"))
        or _normalize_error(result.get("error"))
        or root_error
        or node_error
        or coded_error
    )


def _meta_state(state: dict[str, Any]) -> dict[str, Any]:
    meta = _as_dict(state.get("meta"))
    if "thread_id" not in meta and state.get("thread_id") is not None:
        meta["thread_id"] = str(state.get("thread_id"))
    if "request_id" not in meta and state.get("request_id") is not None:
        meta["request_id"] = str(state.get("request_id"))
    if "entry_mode" not in meta and state.get("entry_mode") is not None:
        meta["entry_mode"] = state.get("entry_mode")
    return meta


def _intent_state(state: dict[str, Any]) -> dict[str, Any]:
    intent = _as_dict(state.get("intent"))
    conversation = _as_dict(state.get("conversation"))
    clarified_task = _as_dict(conversation.get("clarified_task"))
    if "clarified_task" not in intent and clarified_task:
        intent["clarified_task"] = clarified_task
    if "fields" not in intent:
        intent["fields"] = _as_dict(clarified_task.get("fields"))
    return intent


def _world_state(state: dict[str, Any]) -> dict[str, Any]:
    world = _as_dict(state.get("world"))
    if "request_params" not in world:
        world["request_params"] = _legacy_request_params(state)
    if "collection_config" not in world:
        result = _as_dict(state.get("result"))
        data = _as_dict(result.get("data"))
        world["collection_config"] = _as_dict(data.get("collection_config")) or _as_dict(
            state.get("collection_config")
        )
    return world


def _control_state(state: dict[str, Any]) -> dict[str, Any]:
    control = _as_dict(state.get("control"))
    if "current_plan" not in control:
        control["current_plan"] = _legacy_current_plan(state)
    if "stage_status" not in control:
        planning = _as_dict(state.get("planning"))
        dispatch = _as_dict(state.get("dispatch"))
        result = _as_dict(state.get("result"))
        control["stage_status"] = str(
            planning.get("status")
            or dispatch.get("status")
            or result.get("status")
            or state.get("node_status")
            or ""
        )
    return control


def _execution_state(state: dict[str, Any]) -> dict[str, Any]:
    execution = _as_dict(state.get("execution"))
    if "dispatch_summary" not in execution:
        execution["dispatch_summary"] = _legacy_dispatch_summary(state)
    if "subtask_results" not in execution:
        dispatch = _as_dict(state.get("dispatch"))
        execution["subtask_results"] = _as_list(dispatch.get("subtask_results")) or _as_list(
            state.get("subtask_results")
        )
    return execution


def _result_state(state: dict[str, Any]) -> dict[str, Any]:
    result = _as_dict(state.get("result"))
    if "final_error" not in result:
        result["final_error"] = _legacy_final_error(state)
    return result


def coerce_workflow_state(state: Mapping[str, Any] | None) -> WorkflowState:
    graph_state = _as_dict(state)
    return {
        "meta": _meta_state(graph_state),
        "intent": _intent_state(graph_state),
        "world": _world_state(graph_state),
        "control": _control_state(graph_state),
        "execution": _execution_state(graph_state),
        "result": _result_state(graph_state),
    }


def current_plan(state: Mapping[str, Any] | None) -> Any:
    workflow = coerce_workflow_state(state)
    return _as_dict(workflow.get("control")).get("current_plan")


def intent_fields(state: Mapping[str, Any] | None) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    return _as_dict(_as_dict(workflow.get("intent")).get("fields"))


def final_error(state: Mapping[str, Any] | None) -> dict[str, str]:
    workflow = coerce_workflow_state(state)
    return _normalize_error(_as_dict(workflow.get("result")).get("final_error"))

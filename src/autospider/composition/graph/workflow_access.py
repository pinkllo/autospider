"""Workflow-shaped accessors and legacy adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .workflow_state import WorkflowState


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


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


def _fallback_error_state(state: dict[str, Any]) -> dict[str, str]:
    root_error = _as_dict(state.get("error"))
    if root_error.get("code"):
        return {
            "code": str(root_error.get("code") or ""),
            "message": str(root_error.get("message") or ""),
        }
    node_error = _as_dict(state.get("node_error"))
    code = str(node_error.get("code") or state.get("error_code") or "")
    message = str(node_error.get("message") or state.get("error_message") or "")
    if not code and not message:
        return {}
    return {"code": code, "message": message}


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
        intent["fields"] = _as_mapping_list(clarified_task.get("fields"))
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
    return _as_dict(state.get("control"))


def _execution_state(state: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(state.get("execution"))


def _result_state(state: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(state.get("result"))


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


def intent_fields(state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    workflow = coerce_workflow_state(state)
    return _as_mapping_list(_as_dict(workflow.get("intent")).get("fields"))


def final_error(state: Mapping[str, Any] | None) -> dict[str, str]:
    workflow = coerce_workflow_state(state)
    return _normalize_error(_as_dict(workflow.get("result")).get("final_error"))

"""Graph state selectors for typed business access."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .workflow_access import coerce_workflow_state, current_plan, final_error


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _merge_mappings(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, Mapping):
            merged.update(dict(value))
    return merged


def _looks_like_dispatch_summary(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    dispatch_keys = {
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
    return any(key in value for key in dispatch_keys)


def conversation_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return _as_dict(_as_dict(state).get("conversation"))


def planning_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return _as_dict(_as_dict(state).get("planning"))


def dispatch_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return _as_dict(_as_dict(state).get("dispatch"))


def result_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return _as_dict(_as_dict(state).get("result"))


def result_data(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return _as_dict(result_state(state).get("data"))


def request_params(state: Mapping[str, Any] | None) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    world = _as_dict(workflow.get("world"))
    if "request_params" in world:
        return _as_dict(world.get("request_params"))
    graph_state = _as_dict(state)
    params = _as_dict(graph_state.get("normalized_params"))
    if params:
        return params
    params = _as_dict(conversation_state(graph_state).get("normalized_params"))
    if params:
        return params
    return _as_dict(graph_state.get("cli_args"))


def collection_config(state: Mapping[str, Any] | None) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    world = _as_dict(workflow.get("world"))
    if "collection_config" in world:
        return _as_dict(world.get("collection_config"))
    data = result_data(state)
    if isinstance(data.get("collection_config"), Mapping):
        return _as_dict(data.get("collection_config"))
    return _as_dict(_as_dict(state).get("collection_config"))


def collected_urls(state: Mapping[str, Any] | None) -> list[str]:
    data = result_data(state)
    values = data.get("collected_urls")
    if isinstance(values, list):
        return [str(item) for item in values]
    legacy = _as_dict(state).get("collected_urls")
    if isinstance(legacy, list):
        return [str(item) for item in legacy]
    return []


def task_plan(state: Mapping[str, Any] | None) -> Any:
    return current_plan(state)


def dispatch_summary(state: Mapping[str, Any] | None) -> dict[str, Any]:
    workflow = coerce_workflow_state(state)
    execution = _as_dict(workflow.get("execution"))
    if "dispatch_summary" in execution:
        return _as_dict(execution.get("dispatch_summary"))
    graph_state = _as_dict(state)
    dispatch = dispatch_state(graph_state)
    merged = _merge_mappings(
        graph_state.get("dispatch_result"),
        dispatch.get("dispatch_result"),
        dispatch.get("summary"),
    )
    if merged:
        return merged
    root_summary = _as_dict(graph_state.get("summary"))
    if _looks_like_dispatch_summary(root_summary):
        return root_summary
    return {}


def subtask_results(state: Mapping[str, Any] | None) -> list[Any]:
    workflow = coerce_workflow_state(state)
    execution = _as_dict(workflow.get("execution"))
    if "subtask_results" in execution:
        return _as_list(execution.get("subtask_results"))
    dispatch = dispatch_state(state).get("subtask_results")
    if isinstance(dispatch, list) and dispatch:
        return list(dispatch)
    return _as_list(_as_dict(state).get("subtask_results"))


def get_conversation_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return conversation_state(state)


def get_planning_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return planning_state(state)


def get_dispatch_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return dispatch_state(state)


def get_result_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return result_state(state)


def select_result_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    return result_state(state)


def get_result_summary(state: Mapping[str, Any] | None) -> dict[str, Any]:
    graph_state = _as_dict(state)
    result = result_state(graph_state)
    summary = _merge_mappings(
        planning_state(graph_state).get("summary"),
        dispatch_summary(graph_state),
        result.get("summary"),
        graph_state.get("summary"),
    )
    if summary:
        return summary
    return _as_dict(result.get("data"))


def select_summary(
    state: Mapping[str, Any] | None,
    *,
    snapshot_values: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    graph_state = _as_dict(state)
    if graph_state:
        summary = get_result_summary(graph_state)
        if summary:
            return summary
    snapshot_state = _as_dict(snapshot_values)
    return get_result_summary(snapshot_state)


def get_result_artifacts(state: Mapping[str, Any] | None) -> list[dict[str, str]]:
    graph_state = _as_dict(state)
    artifacts = result_state(graph_state).get("artifacts") or graph_state.get("artifacts") or []
    return [
        {"label": str(item.get("label") or ""), "path": str(item.get("path") or "")}
        for item in list(artifacts)
        if isinstance(item, Mapping)
    ]


def select_artifacts(
    state: Mapping[str, Any] | None,
    *,
    snapshot_values: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    graph_state = _as_dict(state)
    if graph_state:
        artifacts = get_result_artifacts(graph_state)
        if artifacts:
            return artifacts
    return get_result_artifacts(snapshot_values)


def get_error_state(state: Mapping[str, Any] | None) -> dict[str, str]:
    error = final_error(state)
    if error:
        return error
    graph_state = _as_dict(state)
    error = _as_dict(graph_state.get("error"))
    if error.get("code"):
        return {
            "code": str(error.get("code") or ""),
            "message": str(error.get("message") or ""),
        }
    node_error = _as_dict(graph_state.get("node_error"))
    return {
        "code": str(node_error.get("code") or graph_state.get("error_code") or ""),
        "message": str(node_error.get("message") or graph_state.get("error_message") or ""),
    }


def select_error(
    state: Mapping[str, Any] | None,
    *,
    snapshot_values: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    graph_state = _as_dict(state)
    error = get_error_state(graph_state)
    if error.get("code"):
        return error
    return get_error_state(snapshot_values)


def get_stage_status(state: Mapping[str, Any] | None) -> str:
    graph_state = _as_dict(state)
    return str(
        planning_state(graph_state).get("status")
        or dispatch_state(graph_state).get("status")
        or result_state(graph_state).get("status")
        or graph_state.get("node_status")
        or ""
    )

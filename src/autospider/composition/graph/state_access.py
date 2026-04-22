"""Graph state selectors for typed business access."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from .workflow_access import coerce_workflow_state, final_error


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


def _enrich_request_params_from_workflow(
    params: dict[str, Any],
    *,
    world: dict[str, Any],
    control: dict[str, Any],
) -> dict[str, Any]:
    if not params:
        return {}
    enriched = dict(params)
    if "world_snapshot" not in enriched:
        enriched["world_snapshot"] = dict(world)
    if "control_snapshot" not in enriched:
        enriched["control_snapshot"] = dict(control)
    if "failure_records" not in enriched:
        enriched["failure_records"] = list(world.get("failure_records") or [])
    return enriched


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
    graph_state = _as_dict(state)
    workflow = coerce_workflow_state(state)
    world = _as_dict(workflow.get("world"))
    control = _as_dict(workflow.get("control"))
    explicit_world = _as_dict(graph_state.get("world")) if "world" in graph_state else {}
    explicit_control = _as_dict(graph_state.get("control")) if "control" in graph_state else {}
    snapshot_world = explicit_world or world
    snapshot_control = explicit_control or control
    if "request_params" in world:
        return _enrich_request_params_from_workflow(
            _as_dict(world.get("request_params")),
            world=snapshot_world,
            control=snapshot_control,
        )
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
    graph_state = _as_dict(state)
    explicit_control = _as_dict(graph_state.get("control")) if "control" in graph_state else {}
    if "task_plan" in explicit_control:
        return explicit_control.get("task_plan")
    workflow = coerce_workflow_state(state)
    return _as_dict(workflow.get("control")).get("task_plan")


def dispatch_summary(state: Mapping[str, Any] | None) -> dict[str, Any]:
    execution = _as_dict(_as_dict(state).get("execution"))
    return _as_dict(execution.get("dispatch_summary"))


def subtask_results(state: Mapping[str, Any] | None) -> list[Any]:
    execution = _as_dict(_as_dict(state).get("execution"))
    return _as_list(execution.get("subtask_results"))


def get_result_summary(state: Mapping[str, Any] | None) -> dict[str, Any]:
    graph_state = _as_dict(state)
    result = result_state(graph_state)
    summary = _merge_mappings(
        dispatch_summary(graph_state),
        result.get("summary"),
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
    artifacts = result_state(graph_state).get("artifacts") or []
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
    graph_state = _as_dict(state)
    if "final_error" in _as_dict(graph_state.get("result")):
        return final_error(graph_state)
    error = final_error(graph_state)
    if error:
        return error
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


StageName = Literal["conversation", "planning", "dispatch", "result"]


def _stage_status_from_state(state: dict[str, Any], stage: StageName) -> str:
    if stage == "conversation":
        return str(conversation_state(state).get("status") or "")
    if stage == "planning":
        return str(planning_state(state).get("status") or "")
    if stage == "dispatch":
        return str(dispatch_state(state).get("status") or "")
    return str(result_state(state).get("status") or "")


def get_stage_status(
    state: Mapping[str, Any] | None,
    *,
    stage: StageName | None = None,
) -> str:
    graph_state = _as_dict(state)
    control = _as_dict(graph_state.get("control"))
    if stage is not None:
        return str(
            _stage_status_from_state(graph_state, stage)
            or control.get("stage_status")
            or graph_state.get("node_status")
            or ""
        )
    return str(
        control.get("stage_status")
        or planning_state(graph_state).get("status")
        or dispatch_state(graph_state).get("status")
        or result_state(graph_state).get("status")
        or graph_state.get("node_status")
        or ""
    )

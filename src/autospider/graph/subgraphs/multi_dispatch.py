from __future__ import annotations

import operator
from typing import Any, Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send, interrupt

from ...common.browser.intervention import BrowserInterventionRequired
from ...common.config import config
from ...contexts.planning.application.handlers import PlanMutationService
from ...contexts.planning.domain import TaskPlan
from ...domain.runtime import SubTaskRuntimeState
from ...pipeline.runtime_controls import resolve_concurrency_settings
from ...pipeline.subtask_runtime import (
    apply_runtime_state_to_plan,
    build_dispatch_summary,
    build_runtime_state,
    inherit_parent_nav_steps,
    resolve_subtask_status,
    restore_subtask,
    subtask_to_payload,
    subtask_signature,
)
from ...pipeline.worker import SubTaskWorker
from ...taskplane_adapter.graph_integration import (
    ensure_taskplane_plan_registered,
    get_taskplane_envelope_id,
    get_taskplane_scheduler,
)
from ...taskplane_adapter.result_bridge import ResultBridge
from ...taskplane_adapter.subtask_bridge import SubtaskBridge


def _use_last(existing: Any, new: Any) -> Any:
    return new


class MultiDispatchState(TypedDict, total=False):
    thread_id: str
    normalized_params: Annotated[dict[str, Any], _use_last]
    control: Annotated[dict[str, Any], _use_last]
    execution: Annotated[dict[str, Any], _use_last]
    task_plan: Annotated[TaskPlan, _use_last]
    plan_knowledge: Annotated[str, _use_last]
    dispatch_queue: list[dict[str, Any]]
    current_batch: list[dict[str, Any]]
    round_subtask_results: Annotated[list[SubTaskRuntimeState], operator.add]
    subtask_results: Annotated[list[SubTaskRuntimeState], _use_last]
    round_expand_requests: Annotated[list[dict[str, Any]], operator.add]
    artifacts: Annotated[list[dict[str, str]], operator.add]
    dispatch_result: dict[str, Any]
    summary: dict[str, Any]
    node_status: str
    node_payload: dict[str, Any]
    node_error: dict[str, str] | None
    taskplane_envelope_id: Annotated[str, _use_last]
    taskplane_has_pending: Annotated[bool, _use_last]


class SubTaskFlowState(TypedDict, total=False):
    thread_id: str
    normalized_params: dict[str, Any]
    task_plan: TaskPlan
    plan_knowledge: str
    taskplane_envelope_id: str
    subtask_payload: dict[str, Any]
    subtask_result: SubTaskRuntimeState
    round_expand_requests: Annotated[list[dict[str, Any]], operator.add]
    round_subtask_results: Annotated[list[SubTaskRuntimeState], operator.add]
    artifacts: Annotated[list[dict[str, str]], operator.add]


def _control_state(state: dict[str, Any]) -> dict[str, Any]:
    return dict(state.get("control") or {})


def _resolved_task_plan(state: dict[str, Any]) -> TaskPlan | None:
    control = _control_state(state)
    task_plan = control.get("task_plan")
    if isinstance(task_plan, TaskPlan):
        return task_plan
    task_plan = state.get("task_plan")
    return task_plan if isinstance(task_plan, TaskPlan) else None


def _resolved_plan_knowledge(state: dict[str, Any]) -> str:
    control = _control_state(state)
    if control.get("plan_knowledge") is not None:
        return str(control.get("plan_knowledge") or "")
    return str(state.get("plan_knowledge") or "")


def _resolved_thread_id(state: dict[str, Any], plan: TaskPlan) -> str:
    return str(state.get("thread_id") or "").strip() or str(plan.plan_id or "")


def _taskplane_scheduler(state: dict[str, Any], plan: TaskPlan):
    return get_taskplane_scheduler(
        thread_id=_resolved_thread_id(state, plan),
        plan_id=plan.plan_id,
    )


def _taskplane_envelope_id(state: dict[str, Any], plan: TaskPlan) -> str:
    envelope_id = str(state.get("taskplane_envelope_id") or "").strip()
    if envelope_id:
        return envelope_id
    return get_taskplane_envelope_id(
        thread_id=_resolved_thread_id(state, plan),
        plan_id=plan.plan_id,
    )


def route_after_feedback(state: dict[str, Any]) -> str:
    control = dict(state.get("control") or {})
    active_strategy = dict(control.get("active_strategy") or {})
    strategy_name = str(active_strategy.get("name") or "")
    if strategy_name == "replan":
        return "replan"
    if strategy_name == "aggregate":
        return "aggregate"
    raise ValueError(f"unknown_feedback_route: {strategy_name or 'missing'}")


def _subtask_signature(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return subtask_signature(payload)


def _restore_subtask(payload: dict[str, Any]):
    return restore_subtask(payload)


def _inherit_parent_nav_steps(payload: dict[str, Any], plan: TaskPlan) -> dict[str, Any]:
    return inherit_parent_nav_steps(payload, plan)


def _resolve_runtime_replan_max_children(params: dict[str, Any]) -> int:
    default_value = int(config.planner.runtime_subtasks_max_children or 0)
    raw_value = params.get("runtime_subtask_max_children")
    try:
        resolved = int(raw_value) if raw_value is not None else default_value
    except (TypeError, ValueError):
        resolved = default_value
    return max(0, resolved)


def _resolve_runtime_subtasks_use_main_model(params: dict[str, Any]) -> bool:
    default_value = bool(config.planner.runtime_subtasks_use_main_model)
    raw_value = params.get("runtime_subtasks_use_main_model")
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() not in {"0", "false", "no", "off", ""}


def _resolve_dispatch_batch_size(state: MultiDispatchState) -> int:
    return resolve_concurrency_settings(_normalized_params(state)).max_concurrent


def _normalized_params(state: MultiDispatchState) -> dict[str, Any]:
    return dict(state.get("normalized_params") or {})


def _dispatch_output_dir(state: MultiDispatchState) -> str:
    return str(_normalized_params(state).get("output_dir") or "output")


def _subtask_params(state: SubTaskFlowState) -> dict[str, Any]:
    return dict(state.get("normalized_params") or {})


def _resolve_subtask_status(result: dict[str, Any]):
    return resolve_subtask_status(result)


def _is_grouped_category_subtask(subtask) -> bool:
    scope = dict(getattr(subtask, "scope", {}) or {})
    scope_key = str(scope.get("key") or "").strip().lower()
    if scope_key.startswith("category:"):
        return True
    path = scope.get("path")
    if isinstance(path, (list, tuple)) and any(str(item or "").strip() for item in path):
        return True
    return bool(str(scope.get("label") or "").strip())


def _resolve_subtask_target_url_count(subtask, params: dict[str, Any]) -> int | None:
    if subtask.target_url_count is not None:
        return int(subtask.target_url_count)
    if getattr(subtask, "per_subtask_target_count", None) is not None and _is_grouped_category_subtask(subtask):
        return int(subtask.per_subtask_target_count)
    if params.get("target_url_count") is not None:
        return int(params["target_url_count"])
    if getattr(subtask, "per_subtask_target_count", None) is not None:
        return int(subtask.per_subtask_target_count)
    return None


def _build_subtask_result(
    subtask,
    *,
    status,
    error: str = "",
    result: dict[str, Any] | None = None,
    expand_request: dict[str, Any] | None = None,
) -> SubTaskRuntimeState:
    return build_runtime_state(
        subtask,
        status=status,
        error=error,
        result=result,
        expand_request=expand_request,
    )


def _apply_result_to_plan(plan: TaskPlan, result_item: SubTaskRuntimeState) -> None:
    apply_runtime_state_to_plan(plan, result_item)


def _build_dispatch_summary(plan: TaskPlan, subtask_results: list[SubTaskRuntimeState]) -> dict[str, Any]:
    return build_dispatch_summary(plan, subtask_results)


def _dispatch_state_payload(
    *,
    status: str,
    task_plan: TaskPlan,
    plan_knowledge: str,
    subtask_results: list[SubTaskRuntimeState],
    summary: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "status": status,
        "task_plan": task_plan,
        "plan_knowledge": plan_knowledge,
        "subtask_results": subtask_results,
        "summary": summary,
    }
    payload["dispatch_result"] = summary
    return payload


async def initialize_multi_dispatch(state: MultiDispatchState) -> MultiDispatchState:
    plan = _resolved_task_plan(state)
    if not isinstance(plan, TaskPlan):
        message = "缺少任务计划，无法调度执行"
        return {"node_status": "fatal", "node_error": {"code": "missing_task_plan", "message": message}, "error": {"code": "missing_task_plan", "message": message}}
    envelope_id = await ensure_taskplane_plan_registered(
        thread_id=_resolved_thread_id(state, plan),
        plan=plan,
        request_params=_normalized_params(state),
        source_agent="initialize_multi_dispatch",
    )
    return {
        "dispatch_queue": [],
        "current_batch": list(state.get("current_batch") or []),
        "subtask_results": list(state.get("subtask_results") or []),
        "round_subtask_results": [],
        "round_expand_requests": [],
        "node_status": "ok",
        "node_error": None,
        "taskplane_envelope_id": envelope_id,
        "taskplane_has_pending": bool(plan.subtasks),
    }


async def prepare_dispatch_batch(state: MultiDispatchState) -> MultiDispatchState:
    plan = _resolved_task_plan(state)
    if not isinstance(plan, TaskPlan):
        message = "缺少任务计划，无法准备调度批次"
        return {"node_status": "fatal", "node_error": {"code": "missing_task_plan", "message": message}, "error": {"code": "missing_task_plan", "message": message}}
    scheduler = _taskplane_scheduler(state, plan)
    batch_size = _resolve_dispatch_batch_size(state)
    tickets = await scheduler.pull(batch_size=batch_size)
    batch = [subtask_to_payload(SubtaskBridge.from_ticket(ticket)) for ticket in tickets]
    return {"current_batch": batch, "dispatch_queue": [], "round_subtask_results": [], "round_expand_requests": []}


def route_dispatch_batch(state: MultiDispatchState):
    batch = list(state.get("current_batch") or [])
    if not batch:
        return "complete_dispatch"
    params = _normalized_params(state)
    params["_thread_id"] = str(state.get("thread_id") or "")
    return [
        Send(
            "execute_subtask_flow",
            {
                "thread_id": str(state.get("thread_id") or ""),
                "normalized_params": params,
                "task_plan": _resolved_task_plan(state),
                "plan_knowledge": _resolved_plan_knowledge(state),
                "taskplane_envelope_id": str(state.get("taskplane_envelope_id") or ""),
                "subtask_payload": payload,
            },
        )
        for payload in batch
    ]


async def run_subtask_worker_node(state: SubTaskFlowState):
    subtask = _restore_subtask(state.get("subtask_payload") or {})
    params = _subtask_params(state)
    plan = _resolved_task_plan(state)
    if not isinstance(plan, TaskPlan):
        raise ValueError("missing_task_plan_for_subtask_worker")
    await ensure_taskplane_plan_registered(
        thread_id=_resolved_thread_id(state, plan),
        plan=plan,
        request_params=params,
        source_agent="run_subtask_worker_node",
    )
    scheduler = _taskplane_scheduler(state, plan)
    await scheduler.ack_start(
        subtask.id,
        agent_id=f"sub-worker-{str(state.get('thread_id') or '').strip() or 'unknown'}",
    )
    if subtask.max_pages is None and params.get("max_pages") is not None:
        subtask.max_pages = int(params["max_pages"])
    resolved_target_count = _resolve_subtask_target_url_count(subtask, params)
    if resolved_target_count is not None:
        subtask.target_url_count = resolved_target_count
    while True:
        try:
            worker = SubTaskWorker(
                subtask=subtask,
                fields=list(getattr(plan, "shared_fields", []) or []),
                output_dir=str(params.get("output_dir") or "output"),
                headless=params.get("headless"),
                thread_id=str(params.get("_thread_id") or ""),
                guard_intervention_mode="interrupt",
                consumer_concurrency=int(params["consumer_concurrency"]) if params.get("consumer_concurrency") is not None else None,
                field_explore_count=int(params["field_explore_count"]) if params.get("field_explore_count") is not None else None,
                field_validate_count=int(params["field_validate_count"]) if params.get("field_validate_count") is not None else None,
                selected_skills=list(params.get("selected_skills") or []),
                plan_knowledge=str(state.get("plan_knowledge") or ""),
                task_plan_snapshot=plan.model_dump(mode="python") if isinstance(plan, TaskPlan) else {},
                plan_journal=[entry.model_dump(mode="python") for entry in list(getattr(plan, "journal", []) or [])] if isinstance(plan, TaskPlan) else [],
                pipeline_mode=params.get("pipeline_mode"),
                runtime_subtask_max_children=_resolve_runtime_replan_max_children(params),
                runtime_subtasks_use_main_model=_resolve_runtime_subtasks_use_main_model(params),
                decision_context=dict(params.get("decision_context") or {}),
                world_snapshot=dict(params.get("world_snapshot") or {}),
                control_snapshot=dict(params.get("control_snapshot") or {}),
                failure_records=list(params.get("failure_records") or []),
            )
            result = await worker.execute()
            effective_subtask = _restore_subtask(
                result.get("_effective_subtask") or result.get("effective_subtask") or subtask
            )
            runtime_state = build_runtime_state(
                effective_subtask,
                status=_resolve_subtask_status(result),
                error=str(result.get("error") or "")[:500],
                result=result.get("_pipeline_result") or result,
                expand_request=dict(result.get("expand_request") or {}),
            )
            break
        except BrowserInterventionRequired as exc:
            state["browser_resume"] = interrupt(exc.payload)
    artifacts = []
    if str(result.get("items_file") or "").strip():
        artifacts.append({"label": "subtask_items", "path": str(result["items_file"])})
    return {
        "subtask_result": runtime_state,
        "round_expand_requests": [dict(result.get("expand_request") or {})] if result.get("expand_request") else [],
        "artifacts": artifacts,
    }


async def finalize_subtask_flow(state: SubTaskFlowState) -> SubTaskFlowState:
    result_item = state.get("subtask_result")
    plan = _resolved_task_plan(state)
    if isinstance(plan, TaskPlan) and isinstance(result_item, SubTaskRuntimeState):
        scheduler = _taskplane_scheduler(state, plan)
        await scheduler.report_result(ResultBridge.to_result(result_item))
    updates: SubTaskFlowState = {"round_subtask_results": [result_item] if result_item else [], "round_expand_requests": list(state.get("round_expand_requests") or [])}
    artifacts = list(state.get("artifacts") or [])
    if artifacts:
        updates["artifacts"] = artifacts
    return updates


async def merge_dispatch_round(state: MultiDispatchState) -> MultiDispatchState:
    plan = _resolved_task_plan(state)
    if not isinstance(plan, TaskPlan):
        message = "缺少任务计划，无法合并调度结果"
        return {"node_status": "fatal", "node_error": {"code": "missing_task_plan", "message": message}, "error": {"code": "missing_task_plan", "message": message}}
    accumulated = list(dict(state.get("execution") or {}).get("subtask_results") or [])
    accumulated.extend(list(state.get("round_subtask_results") or []))
    scheduler = _taskplane_scheduler(state, plan)
    envelope_id = _taskplane_envelope_id(state, plan)
    mutation = PlanMutationService().merge_expand_requests(
        plan=plan,
        expand_requests=list(state.get("round_expand_requests") or []),
        pending_queue=[],
        output_dir=_dispatch_output_dir(state),
    )
    progress = await scheduler.get_envelope_progress(envelope_id)
    has_pending = (progress.queued + progress.dispatched + progress.running) > 0
    summary = _build_dispatch_summary(mutation.task_plan, accumulated)
    prior_control = _control_state(state)
    merged_control: dict[str, Any] = {
        "current_plan": dict(prior_control.get("current_plan") or {}),
        "task_plan": mutation.task_plan,
        "plan_knowledge": mutation.plan_knowledge,
        "stage_status": "ok",
    }
    if "active_strategy" in prior_control:
        merged_control["active_strategy"] = dict(prior_control["active_strategy"])
    return {
        "dispatch_queue": [],
        "current_batch": [],
        "execution": {
            "subtask_results": accumulated,
            "dispatch_summary": summary,
        },
        "control": merged_control,
        "round_subtask_results": [],
        "round_expand_requests": [],
        "node_payload": {"dispatch_result": summary},
        "taskplane_envelope_id": envelope_id,
        "taskplane_has_pending": has_pending,
    }


def route_after_merge(state: MultiDispatchState) -> str:
    if str(state.get("node_status") or "ok") != "ok":
        return "error"
    if bool(state.get("taskplane_has_pending")):
        return "dispatch_next_batch"
    return "dispatch_next_batch" if list(state.get("dispatch_queue") or []) else "complete_dispatch"


async def complete_dispatch(state: MultiDispatchState) -> MultiDispatchState:
    plan = _resolved_task_plan(state)
    if not isinstance(plan, TaskPlan):
        message = "缺少任务计划，无法完成调度"
        return {"node_status": "fatal", "node_error": {"code": "missing_task_plan", "message": message}, "error": {"code": "missing_task_plan", "message": message}}
    scheduler = _taskplane_scheduler(state, plan)
    envelope_id = _taskplane_envelope_id(state, plan)
    progress = await scheduler.get_envelope_progress(envelope_id)
    has_pending = (progress.queued + progress.dispatched + progress.running) > 0
    if has_pending:
        message = "TaskPlane 仍有待处理任务，无法完成调度"
        return {"node_status": "fatal", "node_error": {"code": "taskplane_incomplete", "message": message}, "error": {"code": "taskplane_incomplete", "message": message}}
    mutation = PlanMutationService().merge_expand_requests(
        plan=plan,
        expand_requests=[],
        pending_queue=[],
        output_dir=_dispatch_output_dir(state),
    )
    result_items = list(dict(state.get("execution") or {}).get("subtask_results") or [])
    summary = _build_dispatch_summary(mutation.task_plan, result_items)
    prior_control = _control_state(state)
    merged_control: dict[str, Any] = {
        "current_plan": dict(prior_control.get("current_plan") or {}),
        "task_plan": mutation.task_plan,
        "plan_knowledge": mutation.plan_knowledge,
        "stage_status": "ok",
    }
    if "active_strategy" in prior_control:
        merged_control["active_strategy"] = dict(prior_control["active_strategy"])
    return {
        "execution": {
            "subtask_results": result_items,
            "dispatch_summary": summary,
        },
        "control": merged_control,
        "node_status": "ok",
        "node_error": None,
        "node_payload": {"dispatch_result": summary},
        "error": None,
    }


def build_multi_dispatch_subgraph():
    subtask_flow = StateGraph(SubTaskFlowState)
    subtask_flow.add_node("run_subtask_worker", run_subtask_worker_node)
    subtask_flow.add_node("finalize_subtask_flow", finalize_subtask_flow)
    subtask_flow.set_entry_point("run_subtask_worker")
    subtask_flow.add_edge("run_subtask_worker", "finalize_subtask_flow")
    subtask_flow.add_edge("finalize_subtask_flow", END)

    builder = StateGraph(MultiDispatchState)
    builder.add_node("initialize_multi_dispatch", initialize_multi_dispatch)
    builder.add_node("prepare_dispatch_batch", prepare_dispatch_batch)
    builder.add_node("execute_subtask_flow", subtask_flow.compile())
    builder.add_node("merge_dispatch_round", merge_dispatch_round)
    builder.add_node("complete_dispatch", complete_dispatch)
    builder.set_entry_point("initialize_multi_dispatch")
    builder.add_edge("initialize_multi_dispatch", "prepare_dispatch_batch")
    builder.add_conditional_edges("prepare_dispatch_batch", route_dispatch_batch, {"complete_dispatch": "complete_dispatch"})
    builder.add_edge("execute_subtask_flow", "merge_dispatch_round")
    builder.add_conditional_edges("merge_dispatch_round", route_after_merge, {"dispatch_next_batch": "prepare_dispatch_batch", "complete_dispatch": "complete_dispatch", "error": END})
    builder.add_edge("complete_dispatch", END)
    return builder.compile()

from __future__ import annotations

import operator
from datetime import datetime
from pathlib import Path
from typing import Any, Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, Send, interrupt

from ...common.browser.intervention import BrowserInterventionRequired

from ...common.browser import BrowserSession
from ...common.types import SubTask, SubTaskStatus, TaskPlan
from ...crawler.planner import TaskPlanner
from ...pipeline.worker import SubTaskWorker


class MultiDispatchState(TypedDict, total=False):
    thread_id: str
    normalized_params: dict[str, Any]
    task_plan: TaskPlan
    dispatch_queue: list[dict[str, Any]]
    current_batch: list[dict[str, Any]]
    subtask_results: Annotated[list[dict[str, Any]], operator.add]
    spawned_subtasks: Annotated[list[dict[str, Any]], operator.add]
    artifacts: Annotated[list[dict[str, str]], operator.add]
    dispatch_result: dict[str, Any]
    summary: dict[str, Any]
    node_status: str
    node_payload: dict[str, Any]
    node_error: dict[str, str] | None


class SubTaskFlowState(TypedDict, total=False):
    thread_id: str
    normalized_params: dict[str, Any]
    task_plan: TaskPlan
    subtask_payload: dict[str, Any]
    subtask_result: dict[str, Any]
    spawned_subtasks: Annotated[list[dict[str, Any]], operator.add]
    subtask_results: Annotated[list[dict[str, Any]], operator.add]
    artifacts: Annotated[list[dict[str, str]], operator.add]


REPLAN_MAX_CHILDREN = 8


def _artifact(label: str, path: str | Path) -> dict[str, str]:
    return {"label": label, "path": str(path)}


def _subtask_signature(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("name") or "").strip(),
        str(payload.get("list_url") or "").strip(),
        str(payload.get("task_description") or "").strip(),
    )


def _restore_subtask(payload: dict[str, Any]) -> SubTask:
    return SubTask.model_validate(dict(payload or {}))


def _build_subtask_result(
    subtask: SubTask,
    *,
    status: SubTaskStatus,
    error: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_result = dict(result or {})
    return {
        "id": subtask.id,
        "name": subtask.name,
        "list_url": subtask.list_url,
        "task_description": subtask.task_description,
        "status": status.value,
        "error": error,
        "retry_count": int(subtask.retry_count or 0),
        "result_file": str(run_result.get("items_file") or subtask.result_file or ""),
        "collected_count": int(run_result.get("total_urls", 0) or subtask.collected_count or 0),
        "plan_upgrade_request": run_result.get("plan_upgrade_request"),
    }


def _apply_result_to_plan(plan: TaskPlan, result_item: dict[str, Any]) -> None:
    subtask_id = str(result_item.get("id") or "")
    if not subtask_id:
        return
    for subtask in plan.subtasks:
        if subtask.id != subtask_id:
            continue
        status = str(result_item.get("status") or SubTaskStatus.FAILED.value)
        try:
            subtask.status = SubTaskStatus(status)
        except Exception:
            subtask.status = SubTaskStatus.FAILED
        subtask.error = str(result_item.get("error") or "") or None
        subtask.result_file = str(result_item.get("result_file") or "") or None
        subtask.collected_count = int(result_item.get("collected_count", 0) or 0)
        return


def _build_dispatch_summary(plan: TaskPlan, subtask_results: list[dict[str, Any]]) -> dict[str, Any]:
    for item in subtask_results:
        _apply_result_to_plan(plan, item)

    total = len(plan.subtasks)
    completed = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.COMPLETED)
    failed = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.FAILED)
    skipped = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SKIPPED)
    total_collected = sum(int(subtask.collected_count or 0) for subtask in plan.subtasks)
    plan.total_subtasks = total
    plan.updated_at = datetime.now().isoformat()
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "total_collected": total_collected,
    }


def initialize_multi_dispatch(state: MultiDispatchState) -> MultiDispatchState:
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return {
            "node_status": "fatal",
            "node_error": {"code": "missing_task_plan", "message": "缺少任务计划，无法调度执行"},
        }

    queue = list(state.get("dispatch_queue") or [])
    if not queue:
        queue = [subtask.model_dump(mode="python") for subtask in plan.subtasks]

    return {
        "dispatch_queue": queue,
        "current_batch": list(state.get("current_batch") or []),
        "subtask_results": list(state.get("subtask_results") or []),
        "spawned_subtasks": list(state.get("spawned_subtasks") or []),
        "node_status": "ok",
        "node_error": None,
    }


def prepare_dispatch_batch(state: MultiDispatchState) -> MultiDispatchState:
    queue = list(state.get("dispatch_queue") or [])
    return {
        "current_batch": queue,
        "dispatch_queue": [],
        "spawned_subtasks": [],
    }


def route_dispatch_batch(state: MultiDispatchState):
    batch = list(state.get("current_batch") or [])
    if not batch:
        return "complete_dispatch"

    params = dict(state.get("normalized_params") or {})
    plan = state.get("task_plan")
    return [
        Send(
            "execute_subtask_flow",
            {
                "thread_id": str(state.get("thread_id") or ""),
                "normalized_params": params,
                "task_plan": plan,
                "subtask_payload": payload,
            },
        )
        for payload in batch
    ]


async def run_subtask_worker_node(state: SubTaskFlowState):
    subtask = _restore_subtask(dict(state.get("subtask_payload") or {}))
    params = dict(state.get("normalized_params") or {})
    if subtask.target_url_count is None and params.get("target_url_count") is not None:
        subtask.target_url_count = int(params["target_url_count"])

    plan = state.get("task_plan")
    shared_fields = list(getattr(plan, "shared_fields", []) or [])

    try:
        worker = SubTaskWorker(
            subtask=subtask,
            fields=shared_fields,
            output_dir=str(params.get("output_dir") or "output"),
            headless=bool(params.get("headless", False)),
            thread_id=str(state.get("thread_id") or ""),
            guard_intervention_mode="interrupt",
        )
        result = await worker.execute()
    except BrowserInterventionRequired as exc:
        interrupt(exc.payload)
        return await run_subtask_worker_node(state)
    except Exception as exc:  # noqa: BLE001
        result = {"error": str(exc), "items_file": "", "total_urls": 0}

    plan_upgrade_request = result.get("plan_upgrade_request")
    if isinstance(plan_upgrade_request, dict) and bool(plan_upgrade_request.get("requested")):
        return Command(
            goto="runtime_replan_subtasks",
            update={
                "subtask_result": _build_subtask_result(
                    subtask,
                    status=SubTaskStatus.SKIPPED,
                    error=str(plan_upgrade_request.get("reason") or "plan_upgrade_requested")[:500],
                    result=result,
                ),
            },
        )

    pipeline_error = str(result.get("error") or "").strip()
    if pipeline_error:
        status = SubTaskStatus.FAILED
        error = pipeline_error[:500]
    elif int(result.get("total_urls", 0) or 0) <= 0:
        status = SubTaskStatus.FAILED
        error = "no_data_collected"
    else:
        status = SubTaskStatus.COMPLETED
        error = ""

    return {
        "subtask_result": _build_subtask_result(subtask, status=status, error=error, result=result),
        "artifacts": [
            _artifact("subtask_items", result["items_file"])
            for _ in [1]
            if str(result.get("items_file") or "").strip()
        ],
    }


async def runtime_replan_subtasks(state: SubTaskFlowState) -> SubTaskFlowState:
    subtask = _restore_subtask(dict(state.get("subtask_payload") or {}))
    params = dict(state.get("normalized_params") or {})
    planner_request = str(subtask.task_description or "").strip()
    reason = str((state.get("subtask_result") or {}).get("error") or "").strip()
    if reason and reason not in planner_request:
        planner_request = f"{planner_request}\n\n执行阶段补充线索：{reason}"

    planner_session = BrowserSession(
        headless=bool(params.get("headless", False)),
        guard_intervention_mode="interrupt",
        guard_thread_id=str(state.get("thread_id") or ""),
    )
    try:
        await planner_session.start()
        planner = TaskPlanner(
            page=planner_session.page,
            site_url=str(subtask.list_url or "").strip(),
            user_request=planner_request,
            output_dir=str(Path(str(params.get("output_dir") or "output")) / f"subtask_{subtask.id}"),
            use_main_model=bool(params.get("runtime_subtasks_use_main_model", False)),
        )
        plan = await planner.plan()
    except BrowserInterventionRequired as exc:
        interrupt(exc.payload)
        return await runtime_replan_subtasks(state)
    except Exception as exc:  # noqa: BLE001
        message = f"runtime_replan_failed: {exc}"[:500]
        return {
            "subtask_result": _build_subtask_result(subtask, status=SubTaskStatus.FAILED, error=message),
            "spawned_subtasks": [],
        }
    finally:
        await planner_session.stop()

    spawned_subtasks: list[dict[str, Any]] = []
    for index, candidate in enumerate(list(plan.subtasks or [])[:REPLAN_MAX_CHILDREN], start=1):
        child = candidate.model_copy(deep=True)
        child.parent_id = subtask.id
        child.depth = int(subtask.depth or 0) + 1
        child.created_by = "runtime_plan"
        child.runtime_plan_attempted = False
        child.priority = int(subtask.priority or 0) * 100 + index
        child.status = SubTaskStatus.PENDING
        child.retry_count = 0
        child.error = None
        child.result_file = None
        child.collected_count = 0
        if not child.fields:
            child.fields = list(subtask.fields or [])
        if child.max_pages is None:
            child.max_pages = subtask.max_pages
        if child.target_url_count is None:
            child.target_url_count = subtask.target_url_count or params.get("target_url_count")
        spawned_subtasks.append(child.model_dump(mode="python"))

    if not spawned_subtasks:
        return {
            "subtask_result": _build_subtask_result(
                subtask,
                status=SubTaskStatus.FAILED,
                error="plan_upgrade_requested_but_no_subtasks_generated",
            ),
            "spawned_subtasks": [],
        }

    return {
        "subtask_result": _build_subtask_result(
            subtask,
            status=SubTaskStatus.SKIPPED,
            error=f"delegated_to_runtime_plan: spawned={len(spawned_subtasks)}",
        ),
        "spawned_subtasks": spawned_subtasks,
    }


def finalize_subtask_flow(state: SubTaskFlowState) -> SubTaskFlowState:
    result_item = dict(state.get("subtask_result") or {})
    updates: SubTaskFlowState = {
        "subtask_results": [result_item] if result_item else [],
        "spawned_subtasks": list(state.get("spawned_subtasks") or []),
    }
    artifacts = list(state.get("artifacts") or [])
    if artifacts:
        updates["artifacts"] = artifacts
    return updates


def merge_dispatch_round(state: MultiDispatchState) -> MultiDispatchState:
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return {
            "node_status": "fatal",
            "node_error": {"code": "missing_task_plan", "message": "缺少任务计划，无法合并调度结果"},
        }

    known = {_subtask_signature(subtask.model_dump(mode="python")) for subtask in plan.subtasks}
    queue: list[dict[str, Any]] = []
    for payload in list(state.get("spawned_subtasks") or []):
        signature = _subtask_signature(payload)
        if signature in known:
            continue
        known.add(signature)
        plan.subtasks.append(_restore_subtask(payload))
        queue.append(payload)

    summary = _build_dispatch_summary(plan, list(state.get("subtask_results") or []))
    return {
        "task_plan": plan,
        "dispatch_queue": queue,
        "current_batch": [],
        "spawned_subtasks": [],
        "summary": summary,
    }


def route_after_merge(state: MultiDispatchState) -> str:
    if str(state.get("node_status") or "ok") != "ok":
        return "error"
    if list(state.get("dispatch_queue") or []):
        return "dispatch_next_batch"
    return "complete_dispatch"


def complete_dispatch(state: MultiDispatchState) -> MultiDispatchState:
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return {
            "node_status": "fatal",
            "node_error": {"code": "missing_task_plan", "message": "缺少任务计划，无法完成调度"},
        }

    summary = _build_dispatch_summary(plan, list(state.get("subtask_results") or []))
    return {
        "task_plan": plan,
        "dispatch_result": summary,
        "summary": summary,
        "node_status": "ok",
        "node_error": None,
        "node_payload": {"dispatch_result": summary},
    }


def build_multi_dispatch_subgraph():
    subtask_flow = StateGraph(SubTaskFlowState)
    subtask_flow.add_node("run_subtask_worker", run_subtask_worker_node)
    subtask_flow.add_node("runtime_replan_subtasks", runtime_replan_subtasks)
    subtask_flow.add_node("finalize_subtask_flow", finalize_subtask_flow)
    subtask_flow.set_entry_point("run_subtask_worker")
    subtask_flow.add_edge("run_subtask_worker", "finalize_subtask_flow")
    subtask_flow.add_edge("runtime_replan_subtasks", "finalize_subtask_flow")
    subtask_flow.add_edge("finalize_subtask_flow", END)

    builder = StateGraph(MultiDispatchState)
    builder.add_node("initialize_multi_dispatch", initialize_multi_dispatch)
    builder.add_node("prepare_dispatch_batch", prepare_dispatch_batch)
    builder.add_node("execute_subtask_flow", subtask_flow.compile())
    builder.add_node("merge_dispatch_round", merge_dispatch_round)
    builder.add_node("complete_dispatch", complete_dispatch)
    builder.set_entry_point("initialize_multi_dispatch")
    builder.add_edge("initialize_multi_dispatch", "prepare_dispatch_batch")
    builder.add_conditional_edges(
        "prepare_dispatch_batch",
        route_dispatch_batch,
        {"complete_dispatch": "complete_dispatch"},
    )
    builder.add_edge("execute_subtask_flow", "merge_dispatch_round")
    builder.add_conditional_edges(
        "merge_dispatch_round",
        route_after_merge,
        {
            "dispatch_next_batch": "prepare_dispatch_batch",
            "complete_dispatch": "complete_dispatch",
            "error": END,
        },
    )
    builder.add_edge("complete_dispatch", END)
    return builder.compile()

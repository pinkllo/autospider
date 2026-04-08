"""能力执行节点。"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from langgraph.types import interrupt

from ...contracts import AggregationFailure
from ...common.browser.intervention import BrowserInterventionRequired
from ...domain.planning import TaskPlan
from ...services import (
    AggregationService,
    CollectionService,
    FieldService,
    PipelineExecutionService,
    PlanningService,
)
from ...services.service_utils import build_execution_context, build_execution_request

RETRY_DELAYS = (1.0, 2.0)


def _ok(
    payload: dict[str, Any] | None = None,
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    resolved_payload = payload or {}
    return {
        "node_status": "ok",
        "node_payload": resolved_payload,
        "result_context": resolved_payload,
        "node_artifacts": artifacts or [],
        "node_error": None,
        "result": {
            "status": "ok",
            "data": resolved_payload,
            "artifacts": artifacts or [],
        },
        "error": None,
    }


def _fatal(code: str, message: str) -> dict[str, Any]:
    return {
        "node_status": "fatal",
        "node_payload": {},
        "result_context": {},
        "node_artifacts": [],
        "node_error": {"code": code, "message": message},
        "error_code": code,
        "error_message": message,
        "error": {"code": code, "message": message},
    }


def _thread_id(state: dict[str, Any]) -> str:
    return str(state.get("thread_id") or "")


def _node_artifacts(service_result: dict[str, Any]) -> list[dict[str, str]]:
    return list(service_result.get("artifacts") or [])


def _node_payload(service_result: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    result = service_result.get("result")
    if isinstance(result, dict):
        return {"result": result}
    return fallback or {}


def _merge_summary(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(dict(extra or {}))
    return merged


def _extract_pipeline_result(service_result: dict[str, Any]) -> dict[str, Any]:
    nested = service_result.get("pipeline_result") or service_result.get("result")
    if isinstance(nested, dict) and nested:
        return dict(nested)

    keys = {
        "total_urls",
        "success_count",
        "failed_count",
        "success_rate",
        "required_field_success_rate",
        "validation_failure_count",
        "execution_state",
        "outcome_state",
        "terminal_reason",
        "promotion_state",
        "items_file",
        "summary_file",
        "execution_id",
        "durability_state",
    }
    return {key: service_result[key] for key in keys if key in service_result}


def _extract_pipeline_summary(service_result: dict[str, Any], pipeline_result: dict[str, Any]) -> dict[str, Any]:
    summary = service_result.get("summary")
    if isinstance(summary, dict) and summary:
        return dict(summary)

    keys = {
        "total_urls",
        "success_count",
        "failed_count",
        "success_rate",
        "required_field_success_rate",
        "validation_failure_count",
        "execution_state",
        "outcome_state",
        "terminal_reason",
        "promotion_state",
        "execution_id",
        "items_file",
        "durability_state",
    }
    return {key: pipeline_result[key] for key in keys if key in pipeline_result}


async def _run_with_retry(
    runner: Callable[[], Awaitable[dict[str, Any]]],
    *,
    error_code: str,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return await runner()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= len(RETRY_DELAYS):
                break
            await asyncio.sleep(RETRY_DELAYS[attempt])
    return _fatal(error_code, str(last_error or "unknown_error"))


async def _retry_after_browser_interrupt(
    state: dict[str, Any],
    node_result: dict[str, Any],
    retry: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    current_state = dict(state)
    current_result = dict(node_result)
    while True:
        payload = current_result.pop("__browser_intervention__", None)
        if not isinstance(payload, dict):
            return current_result
        resume_payload = interrupt(payload)
        current_state["browser_resume"] = resume_payload
        current_result = await retry(current_state)


async def run_pipeline_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            service_result = await PipelineExecutionService().execute(request=request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        pipeline_result = _extract_pipeline_result(service_result)
        return {
            **_ok(_node_payload(service_result, {"result": pipeline_result}), _node_artifacts(service_result)),
            "pipeline_result": pipeline_result,
            "summary": _extract_pipeline_summary(service_result, pipeline_result),
            "result": {
                "status": "ok",
                "data": {"result": pipeline_result},
                "summary": _extract_pipeline_summary(service_result, pipeline_result),
                "pipeline_result": pipeline_result,
                "artifacts": _node_artifacts(service_result),
            },
        }

    node_result = await _run_with_retry(_runner, error_code="run_pipeline_failed")
    return await _retry_after_browser_interrupt(state, node_result, run_pipeline_node)


async def collect_urls_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            service_result = await CollectionService().collect_urls(request=request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        return {
            **_ok(_node_payload(service_result), _node_artifacts(service_result)),
            "collected_urls": list(service_result.get("collected_urls") or []),
            "collection_progress": dict(service_result.get("collection_progress") or {}),
            "summary": dict(service_result.get("summary") or {}),
        }

    node_result = await _run_with_retry(_runner, error_code="collect_urls_failed")
    return await _retry_after_browser_interrupt(state, node_result, collect_urls_node)


async def generate_config_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            service_result = await CollectionService().generate_config(request=request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        return {
            **_ok(_node_payload(service_result), _node_artifacts(service_result)),
            "collection_config": dict(service_result.get("collection_config") or {}),
            "summary": dict(service_result.get("summary") or {}),
        }

    node_result = await _run_with_retry(_runner, error_code="generate_config_failed")
    return await _retry_after_browser_interrupt(state, node_result, generate_config_node)


async def batch_collect_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    collection_config = dict(state.get("collection_config") or {})
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            service_result = await CollectionService().batch_collect(
                request=request,
                state={"collection_config": collection_config},
            )
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        return {
            **_ok(_node_payload(service_result), _node_artifacts(service_result)),
            "collection_config": dict(service_result.get("collection_config") or {}),
            "collected_urls": list(service_result.get("collected_urls") or []),
            "collection_progress": dict(service_result.get("collection_progress") or {}),
            "summary": dict(service_result.get("summary") or {}),
        }

    node_result = await _run_with_retry(_runner, error_code="batch_collect_failed")
    return await _retry_after_browser_interrupt(state, node_result, batch_collect_node)


async def field_extract_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    collected_urls = list(state.get("collected_urls") or [])
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            service_result = await FieldService().execute(
                request=request,
                state={"collected_urls": collected_urls},
            )
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        return {
            **_ok(_node_payload(service_result), _node_artifacts(service_result)),
            "fields_config": list(service_result.get("fields_config") or []),
            "xpath_result": service_result.get("xpath_result"),
            "summary": dict(service_result.get("summary") or {}),
        }

    node_result = await _run_with_retry(_runner, error_code="field_extract_failed")
    return await _retry_after_browser_interrupt(state, node_result, field_extract_node)


async def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            service_result = await PlanningService().execute(request=request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        task_plan = service_result.get("task_plan")
        subtasks = list(getattr(task_plan, "subtasks", []) or [])
        planner_status = str(service_result.get("planner_status") or "success")
        terminal_reason = str(service_result.get("terminal_reason") or "")
        if planner_status == "error":
            return _fatal(
                "planner_error",
                terminal_reason or "规划阶段发生内部错误",
            )
        if not subtasks:
            return _fatal(
                "planner_no_subtasks",
                "规划阶段未生成任何可执行子任务，请检查站点结构识别结果或补充更明确的分类入口。",
            )

        return {
            **_ok(_node_payload(service_result, {"task_plan": task_plan})),
            "task_plan": task_plan,
            "plan_knowledge": str(service_result.get("plan_knowledge") or ""),
            "summary": dict(service_result.get("summary") or {}),
            "selected_skills": list(service_result.get("selected_skills") or []),
            "planning": {
                "status": "ok",
                "task_plan": task_plan,
                "plan_knowledge": str(service_result.get("plan_knowledge") or ""),
                "selected_skills": list(service_result.get("selected_skills") or []),
                "summary": dict(service_result.get("summary") or {}),
            },
        }

    node_result = await _run_with_retry(_runner, error_code="plan_failed")
    return await _retry_after_browser_interrupt(state, node_result, plan_node)


async def aggregate_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    task_plan = state.get("task_plan")
    if not isinstance(task_plan, TaskPlan):
        return _fatal("missing_task_plan", "缺少任务计划，无法聚合结果")
    request = build_execution_request(params, thread_id=_thread_id(state))
    context = build_execution_context(request)
    dispatch_summary = dict(state.get("summary") or {})

    try:
        service_result = AggregationService().execute(
            context=context,
            task_plan=task_plan,
        )
    except AggregationFailure as exc:
        report = exc.report.model_dump(mode="python")
        summary = _merge_summary(
            dispatch_summary,
            {
                "merged_items": report.get("merged_items", 0),
                "failed_subtasks": report.get("failed_subtasks", 0),
            },
        )
        return {
            **_fatal("aggregate_failed", str(exc)),
            "aggregate_result": report,
            "summary": summary,
            "result": {
                "status": "failed",
                "data": {"aggregate_result": report},
                "summary": summary,
                "aggregate_result": report,
            },
        }

    summary = _merge_summary(dispatch_summary, dict(service_result.get("summary") or {}))
    return {
        **_ok(_node_payload(service_result), _node_artifacts(service_result)),
        "aggregate_result": dict(service_result.get("aggregate_result") or {}),
        "summary": summary,
        "result": {
            "status": "ok",
            "data": dict(service_result.get("result") or {}),
            "summary": summary,
            "aggregate_result": dict(service_result.get("aggregate_result") or {}),
            "artifacts": _node_artifacts(service_result),
        },
    }

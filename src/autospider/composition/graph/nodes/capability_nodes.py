"""能力执行节点。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from langgraph.types import interrupt

from autospider.platform.browser.intervention import BrowserInterventionRequired
from autospider.platform.browser.runtime import BrowserRuntimeSession
from autospider.platform.config.runtime import config
from autospider.contexts.collection import (
    ResultAggregator,
    collect_detail_urls,
    run_field_pipeline,
)
from autospider.contexts.collection.infrastructure.repositories import (
    CollectionProgress,
    load_collection_config,
)
from autospider.contexts.experience.application.use_cases.skill_runtime import SkillRuntime
from autospider.contexts.experience.infrastructure.repositories.skill_repository import (
    SkillRepository as ExperienceSkillRepository,
)
from autospider.contexts.collection.infrastructure.crawler.batch.batch_collector import batch_collect_urls
from autospider.contexts.collection.infrastructure.crawler.explore.config_generator import generate_collection_config
from autospider.contexts.planning.infrastructure.adapters.task_planner import TaskPlanner
from autospider.contexts.planning.domain import TaskPlan
from autospider.composition.graph.planning_payloads import (
    build_planner_control_payload,
    build_planner_world_payload,
)
from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from ..control_types import build_default_recovery_policy
from autospider.contexts.planning.domain import classify_runtime_exception
from ..recovery import RETRY_ACTION, build_recovery_directive
from ..decision_context import build_decision_context
from ..state_access import (
    collection_config as select_collection_config,
    collected_urls as select_collected_urls,
    dispatch_summary as select_dispatch_summary,
    request_params as select_request_params,
    subtask_results as select_subtask_results,
    task_plan as select_task_plan,
)
from ..workflow_access import coerce_workflow_state
from ...pipeline.helpers import (
    build_artifact,
    build_execution_context,
    build_execution_request,
    build_field_definitions,
    materialize_collection_config,
    serialize_xpath_result,
)
from ...pipeline.runner import run_pipeline
from ...pipeline.types import AggregationFailure, AggregationReport
from autospider.platform.shared_kernel.validators import validate_url
from ...taskplane_adapter.graph_integration import register_taskplane_plan


def _ok(
    payload: dict[str, Any] | None = None,
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    resolved_payload = payload or {}
    resolved_artifacts = artifacts or []
    result_payload = {
        "status": "ok",
        "data": resolved_payload,
        "artifacts": resolved_artifacts,
    }
    return {
        "node_status": "ok",
        "node_payload": resolved_payload,
        "result_context": resolved_payload,
        "node_artifacts": resolved_artifacts,
        "node_error": None,
        "result": result_payload,
        "error": None,
    }


def _fatal(
    code: str,
    message: str,
    *,
    failure_records: list[dict[str, Any]] | None = None,
    recovery_directive: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "node_status": "fatal",
        "node_payload": {},
        "result_context": {},
        "node_artifacts": [],
        "node_error": {"code": code, "message": message},
        "error_code": code,
        "error_message": message,
        "error": {"code": code, "message": message},
    }
    if failure_records:
        result["failure_records"] = [dict(item) for item in list(failure_records)]
    if recovery_directive:
        result["recovery_directive"] = dict(recovery_directive)
    return result


def _thread_id(state: dict[str, Any]) -> str:
    meta = dict(state.get("meta") or {})
    return str(meta.get("thread_id") or state.get("thread_id") or "")


def _node_artifacts(service_result: dict[str, Any]) -> list[dict[str, str]]:
    return list(service_result.get("artifacts") or [])


def _node_payload(
    service_result: dict[str, Any], fallback: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = service_result.get("result")
    if isinstance(result, dict):
        return {"result": result}
    return fallback or {}


def _merge_summary(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(dict(extra or {}))
    return merged


def _build_collection_progress(
    *, list_url: str, task_description: str, collected_count: int
) -> dict[str, Any]:
    progress = CollectionProgress(
        status="COMPLETED",
        pause_reason=None,
        list_url=list_url,
        task_description=task_description,
        current_page_num=1,
        collected_count=collected_count,
        backoff_level=0,
        consecutive_success_pages=0,
    )
    return progress.to_payload()


def build_planning_runtime_payload(
    *,
    plan: TaskPlan,
    plan_knowledge: str,
    request_params: dict[str, Any] | None,
    failure_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_request_params = dict(request_params or {})
    # replan 时需要把上一轮失败证据贯穿进 world / request_params，否则下一轮 dispatch
    # 的 SubTaskWorker 会读到空 failure_records，重蹈覆辙
    resolved_failures = [dict(item) for item in list(failure_records or [])]
    world = build_planner_world_payload(
        plan,
        request_params=resolved_request_params,
        failure_records=resolved_failures,
    )
    control = build_planner_control_payload(plan, request_params=resolved_request_params)
    decision_context = build_decision_context({"world": world, "control": control})
    world_request_params = dict(resolved_request_params)
    world_request_params.update(
        {
            "plan_knowledge": str(plan_knowledge or ""),
            "decision_context": decision_context,
            "failure_records": list(world.get("failure_records") or []),
        }
    )
    world["request_params"] = dict(world_request_params)
    world_model = dict(world.get("world_model") or {})
    world_model["request_params"] = dict(world_request_params)
    world["world_model"] = world_model
    enriched_request_params = dict(world_request_params)
    enriched_request_params["world_snapshot"] = dict(world)
    enriched_request_params["control_snapshot"] = dict(control)
    control["task_plan"] = plan
    control["plan_knowledge"] = str(plan_knowledge or "")
    return {
        "world": world,
        "control": control,
        "decision_context": decision_context,
        "request_params": enriched_request_params,
    }


def _resolve_recovery_retry_budget(state: dict[str, Any]) -> int:
    default = build_default_recovery_policy().max_retries
    params = select_request_params(state)
    decision_context = dict(params.get("decision_context") or {})
    recovery_policy = dict(
        decision_context.get("recovery_policy") or params.get("recovery_policy") or {}
    )
    try:
        return max(int(recovery_policy.get("max_retries", default) or 0), 0)
    except (TypeError, ValueError):
        return default


def _merge_failure_records(
    state: dict[str, Any], failure_record: dict[str, Any]
) -> list[dict[str, Any]]:
    params = select_request_params(state)
    existing = [dict(item) for item in list(params.get("failure_records") or [])]
    existing.append(dict(failure_record))
    return existing


def _attach_recovery_directive(
    failure_record: dict[str, Any],
    directive_action: str,
    directive_reason: str,
) -> dict[str, Any]:
    payload = dict(failure_record)
    metadata = dict(payload.get("metadata") or {})
    metadata["recovery_directive"] = directive_action
    metadata["recovery_reason"] = directive_reason
    payload["metadata"] = metadata
    return payload


def _build_recovery_payload(directive_action: str, directive_reason: str) -> dict[str, Any]:
    return {
        "action": directive_action,
        "reason": directive_reason,
    }


async def _execute_with_recovery(
    state: dict[str, Any],
    runner: Callable[[], Awaitable[dict[str, Any]]],
    *,
    error_code: str,
    node_name: str,
) -> dict[str, Any]:
    failure_count = 0
    retry_budget = _resolve_recovery_retry_budget(state)
    while True:
        try:
            return await runner()
        except Exception as exc:  # noqa: BLE001
            failure_record = classify_runtime_exception(component=node_name, error=exc)
            directive = build_recovery_directive(
                failure_record=failure_record,
                failure_count=failure_count,
                max_retries=retry_budget,
            )
            resolved_failure = _attach_recovery_directive(
                failure_record,
                directive.action,
                directive.reason,
            )
            if directive.action != RETRY_ACTION:
                return _fatal(
                    error_code,
                    str(exc or "unknown_error"),
                    failure_records=_merge_failure_records(state, resolved_failure),
                    recovery_directive=_build_recovery_payload(
                        directive.action,
                        directive.reason,
                    ),
                )
            failure_count += 1
            await asyncio.sleep(directive.delay_seconds)


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


async def _plan_request(request) -> dict[str, Any]:
    planner_url = str(request.site_url or request.list_url or "").strip()
    if not planner_url:
        raise RuntimeError("missing_list_url")
    validate_url(planner_url)

    prior_failures = [dict(item) for item in list(request.failure_records or [])]

    session = BrowserRuntimeSession(**BrowserRuntimeSession.build_options(request))
    await session.start()
    try:
        planner = TaskPlanner(
            page=session.page,
            site_url=planner_url,
            user_request=request.request or request.task_description,
            output_dir=request.output_dir,
            planner_intent=request.model_dump(mode="python"),
            prior_failures=prior_failures,
        )
        runtime = SkillRuntime(ExperienceSkillRepository())
        selected_skill_meta = (
            await runtime.get_or_select(
                phase="planner",
                url=planner_url,
                task_context={
                    "request": request.request or request.task_description,
                    "fields": list(request.fields or []),
                },
                llm=planner.llm,
                preselected_skills=list(request.selected_skills or []),
            )
            if planner_url
            else []
        )
        planner.selected_skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "path": skill.path,
                "domain": skill.domain,
            }
            for skill in selected_skill_meta
        ]
        planner.selected_skills_context = runtime.format_selected_skills_context(
            runtime.load_selected_bodies(selected_skill_meta)
        )
        plan = await planner.plan()
    finally:
        await session.stop()

    plan.shared_fields = list(request.fields or [])
    plan.total_subtasks = len(plan.subtasks)
    runtime_payload = build_planning_runtime_payload(
        plan=plan,
        plan_knowledge=planner.render_plan_knowledge(plan),
        request_params=request.model_dump(mode="python"),
        # 让 replan 链路上的失败证据继续流到下一轮 dispatch 的 SubTaskWorker
        failure_records=prior_failures,
    )
    return {
        "task_plan": plan,
        "plan_knowledge": str(runtime_payload["request_params"].get("plan_knowledge") or ""),
        "world": dict(runtime_payload["world"] or {}),
        "control": dict(runtime_payload["control"] or {}),
        "decision_context": dict(runtime_payload["decision_context"] or {}),
        "request_params": dict(runtime_payload["request_params"] or {}),
        "summary": {"total_subtasks": len(plan.subtasks)},
        "planner_status": str(getattr(planner, "planner_status", "success") or "success"),
        "terminal_reason": str(getattr(planner, "terminal_reason", "") or ""),
        "selected_skills": list(planner.selected_skills or []),
        "result": {"task_plan": plan},
    }


async def _run_pipeline_request(request) -> dict[str, Any]:
    fields = build_field_definitions(list(request.fields or []))
    context = build_execution_context(request, fields=fields)
    pipeline_result = await run_pipeline(context)
    summary_payload = pipeline_result.summary
    artifacts: list[dict[str, str]] = []
    if summary_payload.items_file:
        artifacts.append(build_artifact("pipeline_items", summary_payload.items_file))
    artifacts.append(build_artifact("pipeline_summary", summary_payload.summary_file))
    summary = {
        "total_urls": summary_payload.total_urls,
        "success_count": summary_payload.success_count,
        "failed_count": summary_payload.failed_count,
        "success_rate": summary_payload.success_rate,
        "required_field_success_rate": summary_payload.required_field_success_rate,
        "validation_failure_count": summary_payload.validation_failure_count,
        "execution_state": summary_payload.execution_state,
        "outcome_state": summary_payload.outcome_state,
        "terminal_reason": summary_payload.terminal_reason,
        "promotion_state": summary_payload.promotion_state.value,
        "execution_id": summary_payload.execution_id,
        "items_file": summary_payload.items_file,
        "durability_state": summary_payload.durability_state.value,
        "durably_persisted": summary_payload.durably_persisted,
    }
    payload = pipeline_result.to_payload()
    return {
        "pipeline_result": payload,
        "summary": summary,
        "artifacts": artifacts,
        "result": payload,
    }


async def _collect_urls_request(request) -> dict[str, Any]:
    params = request.model_dump(mode="python")
    async with BrowserRuntimeSession.from_request(request) as session:
        result = await collect_detail_urls(
            page=session.page,
            list_url=request.list_url,
            task_description=request.task_description,
            explore_count=int(params.get("explore_count") or 3),
            target_url_count=request.target_url_count,
            max_pages=request.max_pages,
            output_dir=request.output_dir,
            persist_progress=False,
            selected_skills=list(request.selected_skills or []),
        )
    output_dir = Path(request.output_dir)
    collected_urls = list(result.collected_urls)
    return {
        "data": {
            "collected_urls": collected_urls,
            "collection_progress": _build_collection_progress(
                list_url=request.list_url,
                task_description=request.task_description,
                collected_count=len(collected_urls),
            ),
        },
        "summary": {"collected_urls": len(collected_urls)},
        "artifacts": [
            build_artifact("collected_urls_json", output_dir / "collected_urls.json"),
            build_artifact("collected_urls_txt", output_dir / "urls.txt"),
            build_artifact("collector_spider", output_dir / "spider.py"),
        ],
    }


async def _generate_config_request(request) -> dict[str, Any]:
    params = request.model_dump(mode="python")
    async with BrowserRuntimeSession.from_request(request) as session:
        config_result = await generate_collection_config(
            page=session.page,
            list_url=request.list_url,
            task_description=request.task_description,
            explore_count=int(params.get("explore_count") or 3),
            output_dir=request.output_dir,
            persist_progress=False,
            selected_skills=list(request.selected_skills or []),
        )
    output_dir = Path(request.output_dir)
    payload = config_result.to_payload()
    return {
        "data": {"collection_config": payload},
        "summary": {
            "nav_steps": len(config_result.nav_steps),
            "has_common_detail_xpath": bool(config_result.common_detail_xpath),
            "has_pagination_xpath": bool(config_result.pagination_xpath),
            "has_jump_widget_xpath": bool(config_result.jump_widget_xpath),
        },
        "artifacts": [build_artifact("collection_config", output_dir / "collection_config.json")],
    }


async def _batch_collect_request(
    request, collection_config: dict[str, Any] | None
) -> dict[str, Any]:
    config_payload = dict(collection_config or {})
    params = request.model_dump(mode="python")
    config_path = str(params.get("config_path") or "").strip()
    if not config_path and config_payload:
        config_path = str(materialize_collection_config(request.output_dir, config_payload))
    if not config_path:
        raise ValueError("missing_collection_config")

    async with BrowserRuntimeSession.from_request(request) as session:
        result = await batch_collect_urls(
            page=session.page,
            config_path=config_path,
            target_url_count=request.target_url_count,
            max_pages=request.max_pages,
            output_dir=request.output_dir,
            persist_progress=False,
        )

    if not config_payload:
        loaded = load_collection_config(config_path, strict=True)
        if loaded is None:
            raise ValueError("missing_collection_config")
        config_payload = loaded.to_payload()
    output_dir = Path(request.output_dir)
    collected_urls = list(result.collected_urls)
    return {
        "data": {
            "collection_config": config_payload,
            "collected_urls": collected_urls,
            "collection_progress": _build_collection_progress(
                list_url=str(config_payload.get("list_url") or request.list_url or ""),
                task_description=str(
                    config_payload.get("task_description") or request.task_description or ""
                ),
                collected_count=len(collected_urls),
            ),
        },
        "summary": {"collected_urls": len(collected_urls)},
        "artifacts": [
            build_artifact("batch_collected_urls_json", output_dir / "collected_urls.json"),
            build_artifact("batch_collected_urls_txt", output_dir / "urls.txt"),
        ],
    }


async def _extract_fields_request(request, collected_urls: list[str] | None) -> dict[str, Any]:
    explore_count = request.field_explore_count or config.field_extractor.explore_count
    validate_count = request.field_validate_count or config.field_extractor.validate_count
    async with BrowserRuntimeSession.from_request(request) as session:
        result = await run_field_pipeline(
            page=session.page,
            urls=list(collected_urls or []),
            fields=build_field_definitions(list(request.fields or [])),
            output_dir=request.output_dir,
            explore_count=explore_count,
            validate_count=validate_count,
            run_xpath=True,
            selected_skills=list(request.selected_skills or []),
        )
    output_dir = Path(request.output_dir)
    return {
        "data": {
            "fields_config": list(result.get("fields_config") or []),
            "xpath_result": serialize_xpath_result(result.get("xpath_result")),
        },
        "summary": {
            "url_count": len(list(collected_urls or [])),
            "field_count": len(list(request.fields or [])),
        },
        "artifacts": [
            build_artifact("field_extraction_config", output_dir / "extraction_config.json"),
            build_artifact("field_extraction_result", output_dir / "extraction_result.json"),
            build_artifact("field_extracted_items", output_dir / "extracted_items.json"),
        ],
    }


def _aggregate_results(
    context,
    task_plan: TaskPlan,
    subtask_results: list[SubTaskRuntimeState] | None,
) -> dict[str, Any]:
    aggregate_result = AggregationReport.model_validate(
        ResultAggregator().aggregate(
            plan=task_plan,
            output_dir=context.request.output_dir,
            subtask_results=list(subtask_results or []),
        )
    )
    output_dir = Path(context.request.output_dir)
    report = aggregate_result.model_dump(mode="python")
    return {
        "data": {"aggregate_result": report},
        "summary": {
            "merged_items": aggregate_result.merged_items,
            "unique_urls": aggregate_result.unique_urls,
            "eligible_subtasks": aggregate_result.eligible_subtasks,
            "excluded_subtasks": aggregate_result.excluded_subtasks,
            "failed_subtasks": aggregate_result.failed_subtasks,
            "conflict_count": aggregate_result.conflict_count,
        },
        "artifacts": [
            build_artifact("merged_results", output_dir / "merged_results.jsonl"),
            build_artifact("merged_summary", output_dir / "merged_summary.json"),
        ],
    }


async def run_pipeline_node(state: dict[str, Any]) -> dict[str, Any]:
    params = select_request_params(state)
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            service_result = await _run_pipeline_request(request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        pipeline_result = dict(
            service_result.get("pipeline_result") or service_result.get("result") or {}
        )
        summary = dict(service_result.get("summary") or {})
        return {
            **_ok(
                _node_payload(service_result, {"result": pipeline_result}),
                _node_artifacts(service_result),
            ),
            "pipeline_result": pipeline_result,
            "summary": summary,
            "result": {
                "status": "ok",
                "data": {"result": pipeline_result},
                "summary": summary,
                "pipeline_result": pipeline_result,
                "artifacts": _node_artifacts(service_result),
            },
        }

    node_result = await _execute_with_recovery(
        state,
        _runner,
        error_code="run_pipeline_failed",
        node_name="run_pipeline_node",
    )
    return await _retry_after_browser_interrupt(state, node_result, run_pipeline_node)


async def collect_urls_node(state: dict[str, Any]) -> dict[str, Any]:
    params = select_request_params(state)
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            result = await _collect_urls_request(request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        data = dict(result.get("data") or {})
        return {
            **_ok(data, list(result.get("artifacts") or [])),
            "collected_urls": list(data.get("collected_urls") or []),
            "collection_progress": dict(data.get("collection_progress") or {}),
            "summary": dict(result.get("summary") or {}),
        }

    node_result = await _execute_with_recovery(
        state,
        _runner,
        error_code="collect_urls_failed",
        node_name="collect_urls_node",
    )
    return await _retry_after_browser_interrupt(state, node_result, collect_urls_node)


async def generate_config_node(state: dict[str, Any]) -> dict[str, Any]:
    params = select_request_params(state)
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            result = await _generate_config_request(request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        data = dict(result.get("data") or {})
        return {
            **_ok(data, list(result.get("artifacts") or [])),
            "collection_config": dict(data.get("collection_config") or {}),
            "summary": dict(result.get("summary") or {}),
        }

    node_result = await _execute_with_recovery(
        state,
        _runner,
        error_code="generate_config_failed",
        node_name="generate_config_node",
    )
    return await _retry_after_browser_interrupt(state, node_result, generate_config_node)


async def batch_collect_node(state: dict[str, Any]) -> dict[str, Any]:
    params = select_request_params(state)
    request = build_execution_request(params, thread_id=_thread_id(state))
    collection_config = select_collection_config(state)

    async def _runner() -> dict[str, Any]:
        try:
            result = await _batch_collect_request(request, collection_config)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        data = dict(result.get("data") or {})
        return {
            **_ok(data, list(result.get("artifacts") or [])),
            "collection_config": dict(data.get("collection_config") or {}),
            "collected_urls": list(data.get("collected_urls") or []),
            "collection_progress": dict(data.get("collection_progress") or {}),
            "summary": dict(result.get("summary") or {}),
        }

    node_result = await _execute_with_recovery(
        state,
        _runner,
        error_code="batch_collect_failed",
        node_name="batch_collect_node",
    )
    return await _retry_after_browser_interrupt(state, node_result, batch_collect_node)


async def field_extract_node(state: dict[str, Any]) -> dict[str, Any]:
    params = select_request_params(state)
    request = build_execution_request(params, thread_id=_thread_id(state))
    collected_urls = select_collected_urls(state)

    async def _runner() -> dict[str, Any]:
        try:
            result = await _extract_fields_request(request, collected_urls)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        data = dict(result.get("data") or {})
        return {
            **_ok(data, list(result.get("artifacts") or [])),
            "fields_config": list(data.get("fields_config") or []),
            "xpath_result": data.get("xpath_result"),
            "summary": dict(result.get("summary") or {}),
        }

    node_result = await _execute_with_recovery(
        state,
        _runner,
        error_code="field_extract_failed",
        node_name="field_extract_node",
    )
    return await _retry_after_browser_interrupt(state, node_result, field_extract_node)


async def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    params = select_request_params(state)
    request = build_execution_request(params, thread_id=_thread_id(state))

    async def _runner() -> dict[str, Any]:
        try:
            result = await _plan_request(request)
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        task_plan = result.get("task_plan")
        subtasks = list(getattr(task_plan, "subtasks", []) or [])
        planner_status = str(result.get("planner_status") or "success")
        terminal_reason = str(result.get("terminal_reason") or "")
        if planner_status == "error":
            return _fatal("planner_error", terminal_reason or "规划阶段发生内部错误")
        if not subtasks:
            return _fatal(
                "planner_no_subtasks",
                "规划阶段未生成任何可执行子任务，请检查站点结构识别结果或补充更明确的分类入口。",
            )
        envelope_id = await register_taskplane_plan(
            thread_id=_thread_id(state),
            plan=task_plan,
            request_params=dict(result.get("request_params") or {}),
            source_agent="plan_node",
        )
        prior_control = dict(
            coerce_workflow_state(state).get("control") or state.get("control") or {}
        )
        merged_control = {
            **dict(result.get("control") or {}),
            "task_plan": task_plan,
            "plan_knowledge": str(result.get("plan_knowledge") or ""),
            "taskplane_envelope_id": envelope_id,
            "stage_status": "ok",
        }
        # 保留 feedback 决策写入的 active_strategy（含 replan_count），避免 replan 预算被覆盖
        if "active_strategy" in prior_control:
            merged_control["active_strategy"] = dict(prior_control["active_strategy"])
        return {
            **_ok(_node_payload(result, {"task_plan": task_plan})),
            "world": dict(result.get("world") or {}),
            "control": merged_control,
            "normalized_params": dict(result.get("request_params") or {}),
            "taskplane_envelope_id": envelope_id,
        }

    node_result = await _execute_with_recovery(
        state,
        _runner,
        error_code="plan_failed",
        node_name="plan_node",
    )
    return await _retry_after_browser_interrupt(state, node_result, plan_node)


async def aggregate_node(state: dict[str, Any]) -> dict[str, Any]:
    params = select_request_params(state)
    task_plan = select_task_plan(state)
    if not isinstance(task_plan, TaskPlan):
        return _fatal("missing_task_plan", "缺少任务计划，无法聚合结果")
    request = build_execution_request(params, thread_id=_thread_id(state))
    context = build_execution_context(request)
    dispatch_summary = select_dispatch_summary(state)
    subtask_results = select_subtask_results(state)

    try:
        result = _aggregate_results(context, task_plan, subtask_results)
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

    aggregate_data = dict(result.get("data") or {})
    summary = _merge_summary(dispatch_summary, dict(result.get("summary") or {}))
    return {
        **_ok(aggregate_data, _node_artifacts(result)),
        "aggregate_result": dict(aggregate_data.get("aggregate_result") or {}),
        "summary": summary,
        "result": {
            "status": "ok",
            "data": aggregate_data,
            "summary": summary,
            "aggregate_result": dict(aggregate_data.get("aggregate_result") or {}),
            "artifacts": _node_artifacts(result),
        },
    }

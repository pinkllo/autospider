"""能力执行节点。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from ...common.browser import BrowserSession, create_browser_session, shutdown_browser_engine
from ...common.config import config
from ...common.types import TaskPlan
from ...crawler.batch.batch_collector import batch_collect_urls
from ...crawler.explore.config_generator import generate_collection_config
from ...crawler.explore.url_collector import collect_detail_urls
from ...crawler.planner import TaskPlanner
from ...field import FieldDefinition, run_field_pipeline
from ...pipeline import run_pipeline
from ...pipeline.aggregator import ResultAggregator
from ...pipeline.dispatcher import TaskDispatcher

RETRY_DELAYS = (1.0, 2.0)


def _ok(
    payload: dict[str, Any] | None = None,
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "node_status": "ok",
        "node_payload": payload or {},
        "node_artifacts": artifacts or [],
        "node_error": None,
    }


def _fatal(code: str, message: str) -> dict[str, Any]:
    return {
        "node_status": "fatal",
        "node_payload": {},
        "node_artifacts": [],
        "node_error": {"code": code, "message": message},
        "error_code": code,
        "error_message": message,
    }


def _field_definitions_from_dicts(raw_fields: list[dict[str, Any]]) -> list[FieldDefinition]:
    fields: list[FieldDefinition] = []
    for raw in raw_fields:
        if not isinstance(raw, dict):
            continue
        fields.append(
            FieldDefinition(
                name=str(raw.get("name") or ""),
                description=str(raw.get("description") or ""),
                required=bool(raw.get("required", True)),
                data_type=str(raw.get("data_type") or "text"),
                example=raw.get("example"),
            )
        )
    return fields


def _artifact(label: str, path: str | Path) -> dict[str, str]:
    return {"label": label, "path": str(path)}


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


async def run_pipeline_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or {})

    async def _runner() -> dict[str, Any]:
        result = await run_pipeline(
            list_url=str(params.get("list_url") or ""),
            task_description=str(params.get("task_description") or ""),
            fields=_field_definitions_from_dicts(list(params.get("fields") or [])),
            output_dir=str(params.get("output_dir") or "output"),
            headless=bool(params.get("headless", False)),
            explore_count=params.get("field_explore_count"),
            validate_count=params.get("field_validate_count"),
            consumer_concurrency=params.get("consumer_concurrency"),
            max_pages=params.get("max_pages"),
            target_url_count=params.get("target_url_count"),
            pipeline_mode=params.get("pipeline_mode"),
        )
        artifacts: list[dict[str, str]] = []
        if result.get("items_file"):
            artifacts.append(_artifact("pipeline_items", str(result["items_file"])))
        summary_file = Path(str(params.get("output_dir") or "output")) / "pipeline_summary.json"
        artifacts.append(_artifact("pipeline_summary", summary_file))
        return {
            **_ok({"result": result}, artifacts),
            "summary": {
                "total_urls": int(result.get("total_urls", 0) or 0),
                "success_count": int(result.get("success_count", 0) or 0),
                "items_file": str(result.get("items_file", "")),
                "execution_mode_resolved": "single",
            },
        }

    return await _run_with_retry(_runner, error_code="run_pipeline_failed")


async def collect_urls_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        previous_max_pages: int | None = None
        if params.get("max_pages") is not None:
            previous_max_pages = config.url_collector.max_pages
            config.url_collector.max_pages = int(params["max_pages"])
        try:
            async with create_browser_session(
                headless=bool(params.get("headless", False)),
                close_engine=True,
            ) as session:
                result = await collect_detail_urls(
                    page=session.page,
                    list_url=str(params.get("list_url") or ""),
                    task_description=str(params.get("task") or ""),
                    explore_count=int(params.get("explore_count") or 3),
                    target_url_count=params.get("target_url_count"),
                    output_dir=str(params.get("output_dir") or "output"),
                )
        finally:
            if previous_max_pages is not None:
                config.url_collector.max_pages = previous_max_pages

        output_dir = Path(str(params.get("output_dir") or "output"))
        artifacts = [
            _artifact("collected_urls_json", output_dir / "collected_urls.json"),
            _artifact("collected_urls_txt", output_dir / "urls.txt"),
            _artifact("collector_spider", output_dir / "spider.py"),
        ]
        return {
            **_ok({"result": result}, artifacts),
            "summary": {
                "collected_urls": len(result.collected_urls),
            },
        }

    return await _run_with_retry(_runner, error_code="collect_urls_failed")


async def generate_config_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        async with create_browser_session(
            headless=bool(params.get("headless", False)),
            close_engine=True,
        ) as session:
            config_result = await generate_collection_config(
                page=session.page,
                list_url=str(params.get("list_url") or ""),
                task_description=str(params.get("task") or ""),
                explore_count=int(params.get("explore_count") or 3),
                output_dir=str(params.get("output_dir") or "output"),
            )

        output_dir = Path(str(params.get("output_dir") or "output"))
        artifacts = [_artifact("collection_config", output_dir / "collection_config.json")]
        return {
            **_ok({"result": config_result}, artifacts),
            "summary": {
                "nav_steps": len(config_result.nav_steps),
                "has_common_detail_xpath": bool(config_result.common_detail_xpath),
                "has_pagination_xpath": bool(config_result.pagination_xpath),
                "has_jump_widget_xpath": bool(config_result.jump_widget_xpath),
            },
        }

    return await _run_with_retry(_runner, error_code="generate_config_failed")


async def batch_collect_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        previous_max_pages: int | None = None
        if params.get("max_pages") is not None:
            previous_max_pages = config.url_collector.max_pages
            config.url_collector.max_pages = int(params["max_pages"])
        try:
            async with create_browser_session(
                headless=bool(params.get("headless", False)),
                close_engine=True,
            ) as session:
                result = await batch_collect_urls(
                    page=session.page,
                    config_path=str(params.get("config_path") or ""),
                    target_url_count=params.get("target_url_count"),
                    output_dir=str(params.get("output_dir") or "output"),
                )
        finally:
            if previous_max_pages is not None:
                config.url_collector.max_pages = previous_max_pages

        output_dir = Path(str(params.get("output_dir") or "output"))
        artifacts = [
            _artifact("batch_collected_urls_json", output_dir / "collected_urls.json"),
            _artifact("batch_collected_urls_txt", output_dir / "urls.txt"),
        ]
        return {
            **_ok({"result": result}, artifacts),
            "summary": {
                "collected_urls": len(result.collected_urls),
            },
        }

    return await _run_with_retry(_runner, error_code="batch_collect_failed")


async def field_extract_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        use_explore = params.get("field_explore_count")
        if use_explore is None:
            use_explore = config.field_extractor.explore_count
        use_validate = params.get("field_validate_count")
        if use_validate is None:
            use_validate = config.field_extractor.validate_count

        async with create_browser_session(
            headless=bool(params.get("headless", False)),
            close_engine=True,
        ) as session:
            result = await run_field_pipeline(
                page=session.page,
                urls=list(params.get("urls") or []),
                fields=_field_definitions_from_dicts(list(params.get("fields") or [])),
                output_dir=str(params.get("output_dir") or "output"),
                explore_count=use_explore,
                validate_count=use_validate,
                run_xpath=True,
            )

        output_dir = Path(str(params.get("output_dir") or "output"))
        artifacts = [
            _artifact("field_extraction_config", output_dir / "extraction_config.json"),
            _artifact("field_extraction_result", output_dir / "extraction_result.json"),
            _artifact("field_extracted_items", output_dir / "extracted_items.json"),
        ]
        return {
            **_ok({"result": result}, artifacts),
            "summary": {
                "url_count": len(list(params.get("urls") or [])),
                "field_count": len(list(params.get("fields") or [])),
            },
        }

    return await _run_with_retry(_runner, error_code="field_extract_failed")


async def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        planner_session = BrowserSession(headless=bool(params.get("headless", False)))
        await planner_session.start()
        try:
            planner = TaskPlanner(
                page=planner_session.page,
                site_url=str(params.get("site_url") or params.get("list_url") or ""),
                user_request=str(params.get("request") or params.get("task_description") or ""),
                output_dir=str(params.get("output_dir") or "output"),
            )
            plan = await planner.plan()
        finally:
            await planner_session.stop()

        if not plan.subtasks:
            return _fatal("no_subtasks", "未能识别出任何分类/子任务，请检查网站结构或手动指定")

        fields = list(params.get("fields") or [])
        plan.shared_fields = fields
        return {
            **_ok({"task_plan": plan}),
            "task_plan": plan,
            "summary": {"total_subtasks": len(plan.subtasks)},
        }

    return await _run_with_retry(_runner, error_code="plan_failed")


async def dispatch_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return _fatal("missing_task_plan", "缺少任务计划，无法调度执行")

    async def _runner() -> dict[str, Any]:
        dispatcher = TaskDispatcher(
            plan=plan,
            fields=list(plan.shared_fields or []),
            output_dir=str(params.get("output_dir") or "output"),
            headless=bool(params.get("headless", False)),
            max_concurrent=params.get("max_concurrent"),
            enable_runtime_subtasks=params.get("runtime_subtasks"),
            runtime_subtask_max_depth=params.get("runtime_subtask_max_depth"),
            runtime_subtask_max_children=params.get("runtime_subtask_max_children"),
            runtime_subtasks_use_main_model=params.get("runtime_subtasks_use_main_model"),
        )
        dispatch_result = await dispatcher.run()
        return {
            **_ok({"dispatch_result": dispatch_result}),
            "dispatch_result": dispatch_result,
            "summary": dispatch_result,
        }

    return await _run_with_retry(_runner, error_code="dispatch_failed")


async def aggregate_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        return _fatal("missing_task_plan", "缺少任务计划，无法聚合结果")

    async def _runner() -> dict[str, Any]:
        aggregator = ResultAggregator()
        aggregate_result = aggregator.aggregate(
            plan=plan,
            output_dir=str(params.get("output_dir") or "output"),
        )
        dispatch_result = dict(state.get("dispatch_result") or {})
        dispatch_result.update(
            {
                "merged_items": aggregate_result.get("total_items", 0),
                "unique_urls": aggregate_result.get("unique_urls", 0),
            }
        )
        output_dir = Path(str(params.get("output_dir") or "output"))
        artifacts = [
            _artifact("merged_results", output_dir / "merged_results.jsonl"),
            _artifact("merged_summary", output_dir / "merged_summary.json"),
            _artifact("task_progress", output_dir / "task_progress.json"),
        ]
        return {
            **_ok({"aggregate_result": aggregate_result, "dispatch_result": dispatch_result}, artifacts),
            "aggregate_result": aggregate_result,
            "summary": dispatch_result,
        }

    return await _run_with_retry(_runner, error_code="aggregate_failed")


async def execute_single_or_multi(state: dict[str, Any]) -> dict[str, Any]:
    """chat-pipeline 的执行节点（single/multi）。"""
    params = dict(state.get("normalized_params") or {})
    mode = str(params.get("execution_mode_resolved") or "multi")

    if mode == "single":
        return await run_pipeline_node({"normalized_params": params})

    # multi 分支：复用规划/调度/聚合逻辑
    plan_result = await plan_node({"normalized_params": params})
    if plan_result.get("node_status") != "ok":
        return plan_result

    dispatch_state = {
        "normalized_params": params,
        "task_plan": plan_result.get("task_plan"),
    }
    dispatch_result = await dispatch_node(dispatch_state)
    if dispatch_result.get("node_status") != "ok":
        await shutdown_browser_engine()
        return dispatch_result

    aggregate_state = {
        "normalized_params": params,
        "task_plan": plan_result.get("task_plan"),
        "dispatch_result": dispatch_result.get("dispatch_result"),
    }
    aggregate_result = await aggregate_node(aggregate_state)
    await shutdown_browser_engine()
    if aggregate_result.get("node_status") != "ok":
        return aggregate_result

    summary = dict(aggregate_result.get("summary") or {})
    summary["execution_mode_resolved"] = "multi"
    payload = dict(aggregate_result.get("node_payload") or {})
    payload["execution_mode_resolved"] = "multi"
    return {
        **_ok(payload, list(aggregate_result.get("node_artifacts") or [])),
        "summary": summary,
        "task_plan": plan_result.get("task_plan"),
        "dispatch_result": dispatch_result.get("dispatch_result"),
        "aggregate_result": aggregate_result.get("aggregate_result"),
    }

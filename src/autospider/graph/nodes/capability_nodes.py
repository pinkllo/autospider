"""能力执行节点。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from langgraph.types import interrupt

from ...common.browser.intervention import BrowserInterventionRequired

from ...common.browser import BrowserSession, create_browser_session
from ...common.config import config
from ...common.storage.idempotent_io import write_json_idempotent
from ...common.types import SubTask, TaskPlan
from ...crawler.batch.batch_collector import batch_collect_urls
from ...crawler.explore.config_generator import generate_collection_config
from ...crawler.explore.url_collector import collect_detail_urls
from ...crawler.planner import TaskPlanner
from ...field import FieldDefinition, run_field_pipeline
from ...pipeline import run_pipeline
from ...pipeline.aggregator import ResultAggregator

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


def _browser_session_options(state: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return {
        "headless": bool(params.get("headless", False)),
        "guard_intervention_mode": "interrupt",
        "guard_thread_id": str(state.get("thread_id") or ""),
    }


def _build_fallback_plan(params: dict[str, Any]) -> TaskPlan:
    list_url = str(params.get("site_url") or params.get("list_url") or "")
    task_description = str(params.get("request") or params.get("task_description") or "")
    shared_fields = list(params.get("fields") or [])
    fallback_subtask = SubTask(
        id="category_01",
        name="默认任务",
        list_url=list_url,
        task_description=task_description,
        fields=shared_fields,
        max_pages=params.get("max_pages"),
        target_url_count=params.get("target_url_count"),
        created_by="fallback_plan",
    )
    plan_key = json.dumps({"list_url": list_url, "task_description": task_description}, ensure_ascii=False, sort_keys=True)
    return TaskPlan(
        plan_id=hashlib.sha1(plan_key.encode("utf-8")).hexdigest()[:16],
        original_request=task_description,
        site_url=list_url,
        subtasks=[fallback_subtask],
        total_subtasks=1,
        shared_fields=shared_fields,
        created_at="",
        updated_at="",
    )


def _collection_config_payload(config_obj: Any) -> dict[str, Any]:
    return {
        "nav_steps": list(getattr(config_obj, "nav_steps", []) or []),
        "common_detail_xpath": getattr(config_obj, "common_detail_xpath", None),
        "pagination_xpath": getattr(config_obj, "pagination_xpath", None),
        "jump_widget_xpath": getattr(config_obj, "jump_widget_xpath", None),
        "list_url": str(getattr(config_obj, "list_url", "") or ""),
        "task_description": str(getattr(config_obj, "task_description", "") or ""),
    }


def _load_collection_config_payload(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        "nav_steps": list(raw.get("nav_steps") or []),
        "common_detail_xpath": raw.get("common_detail_xpath"),
        "pagination_xpath": raw.get("pagination_xpath"),
        "jump_widget_xpath": raw.get("jump_widget_xpath"),
        "list_url": str(raw.get("list_url") or ""),
        "task_description": str(raw.get("task_description") or ""),
    }


def _materialize_collection_config(output_dir: str | Path, collection_config: dict[str, Any]) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config_path = output_path / "collection_config.json"
    write_json_idempotent(
        config_path,
        dict(collection_config or {}),
        identity_keys=("list_url", "task_description"),
    )
    return config_path


def _collection_progress_payload(*, list_url: str, task_description: str, collected_count: int, current_page_num: int = 1, status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "status": status,
        "pause_reason": None,
        "list_url": list_url,
        "task_description": task_description,
        "current_page_num": current_page_num,
        "collected_count": collected_count,
        "backoff_level": 0,
        "consecutive_success_pages": 0,
    }


def _serialize_xpath_result(raw_result: Any) -> dict[str, Any] | None:
    if not isinstance(raw_result, dict):
        return None
    return {
        "fields": list(raw_result.get("fields") or []),
        "records": list(raw_result.get("records") or []),
        "total_urls": int(raw_result.get("total_urls", 0) or 0),
        "success_count": int(raw_result.get("success_count", 0) or 0),
    }


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
    payload = node_result.pop("__browser_intervention__", None)
    if not isinstance(payload, dict):
        return node_result
    interrupt(payload)
    return await retry(state)


async def run_pipeline_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or {})

    async def _runner() -> dict[str, Any]:
        try:
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
                guard_intervention_mode="interrupt",
                guard_thread_id=str(state.get("thread_id") or ""),
            )
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        artifacts: list[dict[str, str]] = []
        if result.get("items_file"):
            artifacts.append(_artifact("pipeline_items", str(result["items_file"])))
        summary_file = Path(str(params.get("output_dir") or "output")) / "pipeline_summary.json"
        artifacts.append(_artifact("pipeline_summary", summary_file))
        pipeline_result = {
            "total_urls": int(result.get("total_urls", 0) or 0),
            "success_count": int(result.get("success_count", 0) or 0),
            "items_file": str(result.get("items_file", "")),
            "summary_file": str(summary_file),
            "execution_id": str(result.get("execution_id", "")),
        }
        return {
            **_ok({"result": pipeline_result}, artifacts),
            "pipeline_result": pipeline_result,
            "summary": {
                "total_urls": pipeline_result["total_urls"],
                "success_count": pipeline_result["success_count"],
                "items_file": pipeline_result["items_file"],
            },
        }

    node_result = await _run_with_retry(_runner, error_code="run_pipeline_failed")
    return await _retry_after_browser_interrupt(state, node_result, run_pipeline_node)


async def collect_urls_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        previous_max_pages: int | None = None
        if params.get("max_pages") is not None:
            previous_max_pages = config.url_collector.max_pages
            config.url_collector.max_pages = int(params["max_pages"])
        try:
            async with create_browser_session(
                close_engine=True,
                **_browser_session_options(state, params),
            ) as session:
                result = await collect_detail_urls(
                    page=session.page,
                    list_url=str(params.get("list_url") or ""),
                    task_description=str(params.get("task") or ""),
                    explore_count=int(params.get("explore_count") or 3),
                    target_url_count=params.get("target_url_count"),
                    output_dir=str(params.get("output_dir") or "output"),
                    persist_progress=False,
                )
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        finally:
            if previous_max_pages is not None:
                config.url_collector.max_pages = previous_max_pages

        output_dir = Path(str(params.get("output_dir") or "output"))
        collected_urls = list(result.collected_urls)
        collection_progress = _collection_progress_payload(
            list_url=str(params.get("list_url") or ""),
            task_description=str(params.get("task") or ""),
            collected_count=len(collected_urls),
        )
        artifacts = [
            _artifact("collected_urls_json", output_dir / "collected_urls.json"),
            _artifact("collected_urls_txt", output_dir / "urls.txt"),
            _artifact("collector_spider", output_dir / "spider.py"),
        ]
        return {
            **_ok({"result": {"collected_urls": len(collected_urls)}}, artifacts),
            "collected_urls": collected_urls,
            "collection_progress": collection_progress,
            "summary": {"collected_urls": len(collected_urls)},
        }

    node_result = await _run_with_retry(_runner, error_code="collect_urls_failed")
    return await _retry_after_browser_interrupt(state, node_result, collect_urls_node)


async def generate_config_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        try:
            async with create_browser_session(
                close_engine=True,
                **_browser_session_options(state, params),
            ) as session:
                config_result = await generate_collection_config(
                    page=session.page,
                    list_url=str(params.get("list_url") or ""),
                    task_description=str(params.get("task") or ""),
                    explore_count=int(params.get("explore_count") or 3),
                    output_dir=str(params.get("output_dir") or "output"),
                    persist_progress=False,
                )
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        output_dir = Path(str(params.get("output_dir") or "output"))
        collection_config = _collection_config_payload(config_result)
        artifacts = [_artifact("collection_config", output_dir / "collection_config.json")]
        return {
            **_ok({
                "result": {
                    "nav_steps": len(config_result.nav_steps),
                    "has_common_detail_xpath": bool(config_result.common_detail_xpath),
                    "has_pagination_xpath": bool(config_result.pagination_xpath),
                    "has_jump_widget_xpath": bool(config_result.jump_widget_xpath),
                }
            }, artifacts),
            "collection_config": collection_config,
            "summary": {
                "nav_steps": len(config_result.nav_steps),
                "has_common_detail_xpath": bool(config_result.common_detail_xpath),
                "has_pagination_xpath": bool(config_result.pagination_xpath),
                "has_jump_widget_xpath": bool(config_result.jump_widget_xpath),
            },
        }

    node_result = await _run_with_retry(_runner, error_code="generate_config_failed")
    return await _retry_after_browser_interrupt(state, node_result, generate_config_node)


async def batch_collect_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        previous_max_pages: int | None = None
        if params.get("max_pages") is not None:
            previous_max_pages = config.url_collector.max_pages
            config.url_collector.max_pages = int(params["max_pages"])
        collection_config = dict(state.get("collection_config") or {})
        config_path = str(params.get("config_path") or "").strip()
        if not config_path and collection_config:
            config_path = str(_materialize_collection_config(
                str(params.get("output_dir") or "output"),
                collection_config,
            ))
        if not config_path:
            raise ValueError("missing_collection_config")
        try:
            async with create_browser_session(
                close_engine=True,
                **_browser_session_options(state, params),
            ) as session:
                result = await batch_collect_urls(
                    page=session.page,
                    config_path=config_path,
                    target_url_count=params.get("target_url_count"),
                    output_dir=str(params.get("output_dir") or "output"),
                    persist_progress=False,
                )
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        finally:
            if previous_max_pages is not None:
                config.url_collector.max_pages = previous_max_pages

        output_dir = Path(str(params.get("output_dir") or "output"))
        if not collection_config:
            collection_config = _load_collection_config_payload(config_path)
        collected_urls = list(result.collected_urls)
        collection_progress = _collection_progress_payload(
            list_url=str(collection_config.get("list_url") or params.get("list_url") or ""),
            task_description=str(collection_config.get("task_description") or params.get("task") or ""),
            collected_count=len(collected_urls),
        )
        artifacts = [
            _artifact("batch_collected_urls_json", output_dir / "collected_urls.json"),
            _artifact("batch_collected_urls_txt", output_dir / "urls.txt"),
        ]
        return {
            **_ok({"result": {"collected_urls": len(collected_urls)}}, artifacts),
            "collection_config": collection_config,
            "collected_urls": collected_urls,
            "collection_progress": collection_progress,
            "summary": {"collected_urls": len(collected_urls)},
        }

    node_result = await _run_with_retry(_runner, error_code="batch_collect_failed")
    return await _retry_after_browser_interrupt(state, node_result, batch_collect_node)


async def field_extract_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        use_explore = params.get("field_explore_count")
        if use_explore is None:
            use_explore = config.field_extractor.explore_count
        use_validate = params.get("field_validate_count")
        if use_validate is None:
            use_validate = config.field_extractor.validate_count

        urls = list(params.get("urls") or state.get("collected_urls") or [])
        try:
            async with create_browser_session(
                close_engine=True,
                **_browser_session_options(state, params),
            ) as session:
                result = await run_field_pipeline(
                    page=session.page,
                    urls=urls,
                    fields=_field_definitions_from_dicts(list(params.get("fields") or [])),
                    output_dir=str(params.get("output_dir") or "output"),
                    explore_count=use_explore,
                    validate_count=use_validate,
                    run_xpath=True,
                )
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}

        output_dir = Path(str(params.get("output_dir") or "output"))
        fields_config = list(result.get("fields_config") or [])
        xpath_result = _serialize_xpath_result(result.get("xpath_result"))
        artifacts = [
            _artifact("field_extraction_config", output_dir / "extraction_config.json"),
            _artifact("field_extraction_result", output_dir / "extraction_result.json"),
            _artifact("field_extracted_items", output_dir / "extracted_items.json"),
        ]
        return {
            **_ok({
                "result": {
                    "field_count": len(list(params.get("fields") or [])),
                    "url_count": len(urls),
                    "has_xpath_result": bool(xpath_result),
                    "fields_config_count": len(fields_config),
                }
            }, artifacts),
            "fields_config": fields_config,
            "xpath_result": xpath_result,
            "summary": {
                "url_count": len(urls),
                "field_count": len(list(params.get("fields") or [])),
            },
        }

    node_result = await _run_with_retry(_runner, error_code="field_extract_failed")
    return await _retry_after_browser_interrupt(state, node_result, field_extract_node)


async def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    params = dict(state.get("normalized_params") or state.get("cli_args") or {})

    async def _runner() -> dict[str, Any]:
        planner_session = BrowserSession(**_browser_session_options(state, params))
        await planner_session.start()
        try:
            planner = TaskPlanner(
                page=planner_session.page,
                site_url=str(params.get("site_url") or params.get("list_url") or ""),
                user_request=str(params.get("request") or params.get("task_description") or ""),
                output_dir=str(params.get("output_dir") or "output"),
            )
            plan = await planner.plan()
        except BrowserInterventionRequired as exc:
            return {"__browser_intervention__": exc.payload}
        finally:
            await planner_session.stop()

        if not plan.subtasks:
            plan = _build_fallback_plan(params)

        fields = list(params.get("fields") or [])
        plan.shared_fields = fields
        plan.total_subtasks = len(plan.subtasks)
        return {
            **_ok({"task_plan": plan}),
            "task_plan": plan,
            "summary": {"total_subtasks": len(plan.subtasks)},
        }

    node_result = await _run_with_retry(_runner, error_code="plan_failed")
    return await _retry_after_browser_interrupt(state, node_result, plan_node)


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
        ]
        return {
            **_ok({"aggregate_result": aggregate_result, "dispatch_result": dispatch_result}, artifacts),
            "aggregate_result": aggregate_result,
            "summary": dispatch_result,
        }

    return await _run_with_retry(_runner, error_code="aggregate_failed")

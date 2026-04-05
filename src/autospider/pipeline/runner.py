"""并发流水线运行器，用于列表采集和字段提取。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..common.browser import BrowserSession
from ..common.browser.intervention import BrowserInterventionRequired
from ..common.channel.base import URLChannel, URLTask
from ..common.channel.factory import create_url_channel
from ..common.config import config
from ..common.experience import SkillRuntime
from ..common.experience.skill_sedimenter import SkillSedimentationPayload
from ..crawler.explore.url_collector import URLCollector
from ..domain.fields import FieldDefinition
from ..field import BatchFieldExtractor, BatchXPathExtractor
from autospider.common.logger import get_logger
from .finalization import (
    PipelineFinalizationContext,
    PipelineFinalizationDependencies,
    PipelineFinalizer,
    build_execution_id as _build_execution_id_impl,
    build_record_summary as _build_record_summary_impl,
    build_run_record as _build_run_record_impl,
    classify_pipeline_result as _classify_pipeline_result_impl,
    cleanup_output_draft_skill as _cleanup_output_draft_skill_impl,
    commit_items_file as _commit_items_file_impl,
    find_output_draft_skill as _find_output_draft_skill_impl,
    finalize_task_from_record as _finalize_task_from_record_impl,
    load_persisted_run_records as _load_persisted_run_records_impl,
    persist_pipeline_run as _persist_pipeline_run_impl,
    prepare_fields_config as _prepare_fields_config_impl,
    prepare_pipeline_output as _prepare_pipeline_output_impl,
    should_promote_skill as _should_promote_skill_impl,
    strip_draft_markers_from_skill_content as _strip_draft_markers_from_skill_content_impl,
    try_sediment_skill as _try_sediment_skill_impl,
    write_summary as _write_summary_impl,
)
from .orchestration import (
    PipelineRuntimeContext,
    PipelineRuntimeDependencies,
    PipelineSessionBundle,
    create_pipeline_services,
)
from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)


def _prepare_fields_config(
    fields_config: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    return _prepare_fields_config_impl(fields_config)


def _find_output_draft_skill(list_url: str, output_dir: str):
    return _find_output_draft_skill_impl(list_url, output_dir)


def _cleanup_output_draft_skill(list_url: str, output_dir: str) -> None:
    _cleanup_output_draft_skill_impl(list_url, output_dir)


def _classify_pipeline_result(
    *,
    total_urls: int,
    success_count: int,
    state_error: object,
    validation_failures: list[dict],
) -> dict[str, object]:
    return _classify_pipeline_result_impl(
        total_urls=total_urls,
        success_count=success_count,
        state_error=state_error,
        validation_failures=validation_failures,
    )


def _should_promote_skill(
    *,
    state: dict[str, object],
    summary: dict,
    validation_failures: list[dict],
) -> bool:
    return _should_promote_skill_impl(
        state=state,
        summary=summary,
        validation_failures=validation_failures,
    )


def _strip_draft_markers_from_skill_content(content: str) -> str:
    return _strip_draft_markers_from_skill_content_impl(content)


def _build_execution_id(
    *,
    list_url: str,
    task_description: str,
    fields: list[FieldDefinition],
    target_url_count: int | None,
    max_pages: int | None,
    pipeline_mode: str | None,
    thread_id: str,
) -> str:
    return _build_execution_id_impl(
        list_url=list_url,
        task_description=task_description,
        fields=fields,
        target_url_count=target_url_count,
        max_pages=max_pages,
        pipeline_mode=pipeline_mode,
        thread_id=thread_id,
    )


def _prepare_pipeline_output(
    *,
    output_path: Path,
    items_path: Path,
    summary_path: Path,
) -> None:
    _prepare_pipeline_output_impl(
        output_path=output_path,
        items_path=items_path,
        summary_path=summary_path,
    )


def _build_run_record(
    *,
    url: str,
    item: dict,
    success: bool,
    failure_reason: str,
) -> dict:
    return _build_run_record_impl(
        url=url,
        item=item,
        success=success,
        failure_reason=failure_reason,
    )


def _load_persisted_run_records(execution_id: str) -> dict[str, dict]:
    return _load_persisted_run_records_impl(execution_id)


def _build_record_summary(records: dict[str, dict]) -> dict[str, int]:
    return _build_record_summary_impl(records)


def _commit_items_file(items_path: Path, records: dict[str, dict]) -> None:
    _commit_items_file_impl(items_path, records)


async def _finalize_task_from_record(task: URLTask, record: dict) -> None:
    await _finalize_task_from_record_impl(task, record)


def _write_summary(path: Path, summary: dict) -> None:
    _write_summary_impl(path, summary)


def _persist_pipeline_run(context: PipelineFinalizationContext, records: dict[str, dict]) -> None:
    _persist_pipeline_run_impl(context, records)


def _try_sediment_skill(
    *,
    state: dict[str, object],
    payload: SkillSedimentationPayload,
) -> Path | None:
    return _try_sediment_skill_impl(
        state=state,
        payload=payload,
    )


def _set_state_error(state: dict[str, object], error: str) -> None:
    if not state.get("error"):
        state["error"] = error


def _resolve_run_redis_key_prefix(
    *,
    pipeline_mode: str | None,
    redis_key_prefix: str | None,
    execution_id: str,
) -> str | None:
    if redis_key_prefix:
        return redis_key_prefix
    mode = str(pipeline_mode or config.pipeline.mode).strip().lower()
    if mode != "redis":
        return None
    base_prefix = (config.redis.key_prefix or "autospider:urls").strip() or "autospider:urls"
    return f"{base_prefix}:run:{execution_id}"


async def run_pipeline(
    list_url: str,
    task_description: str,
    fields: list[FieldDefinition],
    output_dir: str = "output",
    headless: bool = False,
    explore_count: int | None = None,
    validate_count: int | None = None,
    consumer_concurrency: int | None = None,
    max_pages: int | None = None,
    target_url_count: int | None = None,
    pipeline_mode: str | None = None,
    redis_key_prefix: str | None = None,
    guard_intervention_mode: str = "blocking",
    guard_thread_id: str = "",
    selected_skills: list[dict[str, str]] | None = None,
    plan_knowledge: str = "",
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    execution_id = _build_execution_id(
        list_url=list_url,
        task_description=task_description,
        fields=fields,
        target_url_count=target_url_count,
        max_pages=max_pages,
        pipeline_mode=pipeline_mode,
        thread_id=guard_thread_id,
    )

    explore_count = explore_count or config.field_extractor.explore_count
    validate_count = validate_count or config.field_extractor.validate_count
    consumer_workers = max(
        1,
        int(consumer_concurrency or config.pipeline.consumer_concurrency),
    )
    effective_redis_key_prefix = _resolve_run_redis_key_prefix(
        pipeline_mode=pipeline_mode,
        redis_key_prefix=redis_key_prefix,
        execution_id=execution_id,
    )

    channel, redis_manager = create_url_channel(
        mode=pipeline_mode,
        output_dir=output_dir,
        redis_key_prefix=effective_redis_key_prefix,
    )

    items_path = output_path / "pipeline_extracted_items.jsonl"
    summary_path = output_path / "pipeline_summary.json"
    _prepare_pipeline_output(
        output_path=output_path,
        items_path=items_path,
        summary_path=summary_path,
    )
    run_records = _load_persisted_run_records(execution_id)
    skill_runtime = SkillRuntime()

    summary = {
        "run_id": execution_id,
        "list_url": list_url,
        "task_description": task_description,
        "mode": (pipeline_mode or config.pipeline.mode),
        "total_urls": 0,
        "success_count": 0,
        "consumer_concurrency": consumer_workers,
        "target_url_count": target_url_count,
        "items_file": str(items_path),
        "summary_file": str(summary_path),
        "execution_id": execution_id,
    }

    sessions = PipelineSessionBundle(
        list_session=BrowserSession(
            headless=headless,
            guard_intervention_mode=guard_intervention_mode,
            guard_thread_id=guard_thread_id,
        ),
        detail_session=BrowserSession(
            headless=headless,
            guard_intervention_mode=guard_intervention_mode,
            guard_thread_id=guard_thread_id,
        ),
    )
    await sessions.start()

    runtime_context = PipelineRuntimeContext(
        list_url=list_url,
        task_description=task_description,
        fields=fields,
        output_dir=output_dir,
        headless=headless,
        explore_count=explore_count,
        validate_count=validate_count,
        consumer_workers=consumer_workers,
        max_pages=max_pages,
        target_url_count=target_url_count,
        guard_intervention_mode=guard_intervention_mode,
        guard_thread_id=guard_thread_id,
        selected_skills=selected_skills,
        channel=channel,
        redis_manager=redis_manager,
        run_records=run_records,
        summary=summary,
        tracker=TaskProgressTracker(execution_id),
        skill_runtime=skill_runtime,
        sessions=sessions,
        plan_knowledge=plan_knowledge,
        url_only_mode=len(fields) == 0,
    )

    runtime_deps = PipelineRuntimeDependencies(
        browser_session_factory=BrowserSession,
        collector_cls=URLCollector,
        batch_field_extractor_cls=BatchFieldExtractor,
        batch_xpath_extractor_cls=BatchXPathExtractor,
        prepare_fields_config=_prepare_fields_config,
        set_state_error=_set_state_error,
        collect_tasks=_collect_tasks,
        process_task=_process_task,
        fail_tasks=_fail_tasks,
    )
    services = create_pipeline_services(runtime_context, runtime_deps)

    finalizer = PipelineFinalizer(
        PipelineFinalizationDependencies(
            build_record_summary=_build_record_summary,
            classify_pipeline_result=_classify_pipeline_result,
            persist_pipeline_run=_persist_pipeline_run,
            commit_items_file=_commit_items_file,
            write_summary=_write_summary,
            try_sediment_skill=_try_sediment_skill,
            cleanup_output_draft_skill=_cleanup_output_draft_skill,
        )
    )

    try:
        await asyncio.gather(
            services.producer.run(),
            services.exploration.run(),
            services.consumer_pool.run(),
        )
    finally:
        try:
            await finalizer.finalize(
                PipelineFinalizationContext(
                    list_url=list_url,
                    task_description=task_description,
                    fields=fields,
                    thread_id=guard_thread_id,
                    output_dir=output_dir,
                    output_path=output_path,
                    items_path=items_path,
                    summary_path=summary_path,
                    committed_records=run_records,
                    summary=summary,
                    state=runtime_context.state,
                    collection_config=dict(runtime_context.state.get("collection_config") or {}),
                    extraction_config=dict(runtime_context.state.get("extraction_config") or {}),
                    validation_failures=list(runtime_context.state.get("validation_failures") or []),
                    plan_knowledge=runtime_context.plan_knowledge,
                    tracker=runtime_context.tracker,
                    sessions=sessions,
                )
            )
        finally:
            await channel.close()

    return summary


async def _collect_tasks(
    channel: URLChannel,
    needed: int,
    producer_done: asyncio.Event,
) -> list[URLTask]:
    tasks: list[URLTask] = []
    while len(tasks) < needed:
        batch = await channel.fetch(
            max_items=needed - len(tasks),
            timeout_s=config.pipeline.fetch_timeout_s,
        )
        if not batch:
            if producer_done.is_set():
                break
            continue
        tasks.extend(batch)
    return tasks


async def _process_task(
    extractor: BatchXPathExtractor,
    task: URLTask,
    run_records: dict[str, dict],
    summary_lock: asyncio.Lock,
    tracker: TaskProgressTracker | None = None,
) -> None:
    url = (task.url or "").strip()
    if not url:
        await task.fail_task("empty_url")
        return

    async with summary_lock:
        existing_record = run_records.get(url)

    if existing_record is not None:
        await _finalize_task_from_record(task, existing_record)
        if tracker:
            if existing_record.get("success"):
                await tracker.record_success(url)
            else:
                await tracker.record_failure(url, str(existing_record.get("failure_reason") or ""))
        return

    try:
        record = await extractor._extract_from_url(url)
    except BrowserInterventionRequired:
        raise
    except Exception as exc:  # noqa: BLE001
        run_record = _build_run_record(
            url=url,
            item={"url": url, "_error": f"extractor_exception: {exc}"},
            success=False,
            failure_reason=f"extractor_exception: {exc}",
        )
    else:
        item = {"url": record.url}
        for field_result in record.fields:
            item[field_result.field_name] = field_result.value

        if record.success:
            run_record = _build_run_record(
                url=url,
                item=item,
                success=True,
                failure_reason="",
            )
        else:
            run_record = _build_run_record(
                url=url,
                item=item,
                success=False,
                failure_reason=_build_error_reason(record),
            )

    async with summary_lock:
        run_records[url] = run_record

    await _finalize_task_from_record(task, run_record)

    if tracker:
        if run_record.get("success"):
            await tracker.record_success(url)
        else:
            await tracker.record_failure(url, run_record.get("failure_reason", ""))


async def _fail_tasks(tasks: list[URLTask], reason: str) -> None:
    for task in tasks:
        await task.fail_task(reason)


def _build_error_reason(record) -> str:
    errors = []
    for field_result in record.fields:
        if field_result.error:
            errors.append(field_result.error)
    return "; ".join(errors) if errors else "extraction_failed"

"""并发流水线运行器，用于列表采集和字段提取。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from autospider.contexts.collection import DetailPageWorker, URLCollector
from autospider.contexts.collection.infrastructure.channel.base import URLTask
from autospider.contexts.collection.infrastructure.channel.factory import create_url_channel
from autospider.contexts.experience.application.use_cases.skill_runtime import SkillRuntime
from autospider.contexts.experience.infrastructure.repositories.skill_repository import (
    SkillRepository as ExperienceSkillRepository,
)
from autospider.contexts.planning.domain import SITE_DEFENSE_CATEGORY, classify_runtime_exception
from autospider.platform.browser.intervention import BrowserInterventionRequired
from autospider.platform.browser.runtime import BrowserRuntimeSession
from autospider.platform.config.runtime import config
from autospider.platform.observability.logger import get_logger

from .finalization import (
    PipelineFinalizationDependencies,
    PipelineFinalizer,
    build_record_summary as _build_record_summary,
    classify_pipeline_result as _classify_pipeline_result,
    commit_items_file as _commit_items_file,
    finalize_task_from_record as _finalize_task_from_record,
    load_persisted_run_records as _load_persisted_run_records,
    persist_pipeline_records as _persist_pipeline_records,
    promote_staged_output as _promote_staged_output,
    prepare_pipeline_output as _prepare_pipeline_output,
    write_summary as _write_summary,
)
from .orchestration import (
    PipelineRuntimeDependencies,
    PipelineRuntimeState,
    PipelineServiceBundle,
    PipelineSessionBundle,
    create_pipeline_services,
)
from .progress_tracker import TaskProgressTracker
from .run_store_async import (
    _ack_persisted_item,
    _claim_persisted_item,
    _commit_persisted_item,
    _fail_persisted_item,
    _persist_run_snapshot,
    _release_inflight_items_for_resume,
    _release_persisted_claim,
)
from .runtime_setup import (
    PipelineRunResolved,
    build_finalization_context,
    build_pipeline_summary,
    build_runtime_context,
    resolve_pipeline_run,
)
from .task_processing import (
    process_task as _process_task_impl,
    restore_resume_tracker_progress as _restore_resume_tracker_progress_impl,
    set_state_error as _set_state_error,
)
from .types import ExecutionContext, PipelineRunResult

logger = get_logger(__name__)


def _resolve_run_redis_key_prefix(
    *,
    pipeline_mode: str | None,
    redis_key_prefix: str | None,
    execution_id: str,
) -> str | None:
    if redis_key_prefix:
        return redis_key_prefix
    mode = str(config.pipeline.mode if pipeline_mode is None else pipeline_mode).strip().lower()
    if mode != "redis":
        return None
    base_prefix = (config.redis.key_prefix or "autospider:urls").strip() or "autospider:urls"
    return f"{base_prefix}:run:{execution_id}"


def _build_pipeline_run_result(
    summary: dict[str, Any],
    *,
    summary_file: Path,
) -> PipelineRunResult:
    return PipelineRunResult.from_raw(summary, summary_file=str(summary_file))


async def _restore_resume_tracker_progress(
    tracker: TaskProgressTracker,
    records: dict[str, dict],
) -> None:
    await _restore_resume_tracker_progress_impl(
        tracker,
        records,
        build_record_summary=_build_record_summary,
    )


async def _initialize_tracker(
    tracker: TaskProgressTracker,
    *,
    is_resume: bool,
    run_records: dict[str, dict[str, Any]],
) -> None:
    await tracker.set_runtime_state(
        {
            "stage": "starting",
            "resume_mode": "resume" if is_resume else "fresh",
        }
    )
    if is_resume:
        await _restore_resume_tracker_progress(tracker, run_records)


def _build_sessions(
    resolved: PipelineRunResolved,
    context: ExecutionContext,
) -> PipelineSessionBundle:
    return PipelineSessionBundle(
        list_session=BrowserRuntimeSession(
            headless=resolved.headless,
            guard_intervention_mode=resolved.guard_intervention_mode,
            guard_thread_id=resolved.guard_thread_id,
            budget_key=resolved.execution_id,
            global_browser_budget=context.global_browser_budget,
        ),
    )


async def _persist_initial_snapshot(
    context: ExecutionContext,
    *,
    resolved: PipelineRunResolved,
    summary: dict[str, Any],
) -> None:
    await _persist_run_snapshot(
        identity=context.identity,
        fields=resolved.fields,
        execution_id=resolved.execution_id,
        thread_id=resolved.guard_thread_id,
        output_dir=resolved.output_dir,
        pipeline_mode=context.pipeline_mode,
        summary=summary,
        plan_knowledge=context.plan_knowledge,
        task_plan=dict(context.task_plan_snapshot or {}),
        plan_journal=list(context.plan_journal or []),
    )


def _build_runtime_dependencies() -> PipelineRuntimeDependencies:
    return PipelineRuntimeDependencies(
        browser_session_factory=BrowserRuntimeSession,
        collector_cls=URLCollector,
        detail_page_worker_cls=DetailPageWorker,
        set_state_error=_set_state_error,
        process_task=_process_task,
    )


def _build_finalizer() -> PipelineFinalizer:
    return PipelineFinalizer(
        PipelineFinalizationDependencies(
            build_record_summary=_build_record_summary,
            classify_pipeline_result=_classify_pipeline_result,
            persist_pipeline_records=_persist_pipeline_records,
            commit_items_file=_commit_items_file,
            write_summary=_write_summary,
            promote_output=_promote_staged_output,
        )
    )


async def _run_services(
    services: PipelineServiceBundle,
    *,
    runtime_state: PipelineRuntimeState,
    tracker: TaskProgressTracker,
) -> None:
    try:
        await asyncio.gather(services.producer.run(), services.consumer_pool.run())
    except BrowserInterventionRequired:
        runtime_state.terminal_reason = runtime_state.terminal_reason or "browser_intervention"
        if not runtime_state.failure_category:
            runtime_state.failure_category = SITE_DEFENSE_CATEGORY
            runtime_state.failure_detail = runtime_state.failure_detail or "browser_intervention"
        await tracker.set_runtime_state(
            {
                "stage": "interrupted",
                "terminal_reason": "browser_intervention",
            }
        )
        raise


async def _finalize_pipeline(
    *,
    finalizer: PipelineFinalizer,
    context: ExecutionContext,
    resolved: PipelineRunResolved,
    summary: dict[str, Any],
    runtime_context: Any,
    sessions: PipelineSessionBundle,
    channel: Any,
) -> None:
    try:
        await finalizer.finalize(
            build_finalization_context(
                context,
                resolved=resolved,
                summary=summary,
                runtime_context=runtime_context,
                sessions=sessions,
                committed_records=_load_persisted_run_records(resolved.execution_id),
            )
        )
    finally:
        await channel.close()


def _attach_runtime_summary(summary: dict[str, Any], runtime_state: PipelineRuntimeState) -> None:
    summary["collection_config"] = dict(runtime_state.collection_config or {})
    summary["extraction_config"] = dict(runtime_state.extraction_config or {})
    summary["extraction_evidence"] = list(runtime_state.extraction_evidence or [])
    summary["validation_failures"] = list(runtime_state.validation_failures or [])


async def run_pipeline(context: ExecutionContext) -> PipelineRunResult:
    resolved = resolve_pipeline_run(
        context,
        explore_count_default=config.field_extractor.explore_count,
        validate_count_default=config.field_extractor.validate_count,
    )
    resolved.output_path.mkdir(parents=True, exist_ok=True)
    summary = build_pipeline_summary(resolved)
    summary["mode"] = context.pipeline_mode.value
    channel = create_url_channel(
        mode=context.pipeline_mode.value,
        output_dir=resolved.output_dir,
        redis_key_prefix=_resolve_run_redis_key_prefix(
            pipeline_mode=context.pipeline_mode.value,
            redis_key_prefix=None,
            execution_id=resolved.execution_id,
        ),
    )
    skill_runtime = SkillRuntime(ExperienceSkillRepository())
    _prepare_pipeline_output(
        output_path=resolved.output_path,
        items_path=resolved.staging_items_path,
        summary_path=resolved.staging_summary_path,
    )
    if resolved.is_resume:
        await _release_inflight_items_for_resume(resolved.execution_id)
    run_records = _load_persisted_run_records(resolved.execution_id) if resolved.is_resume else {}
    tracker = TaskProgressTracker(resolved.execution_id)
    await _initialize_tracker(tracker, is_resume=resolved.is_resume, run_records=run_records)
    sessions = _build_sessions(resolved, context)
    await sessions.start()
    runtime_context = build_runtime_context(
        context,
        resolved=resolved,
        channel=channel,
        run_records=run_records,
        summary=summary,
        tracker=tracker,
        skill_runtime=skill_runtime,
        sessions=sessions,
    )
    await _persist_initial_snapshot(context, resolved=resolved, summary=summary)
    services = create_pipeline_services(runtime_context, _build_runtime_dependencies())
    finalizer = _build_finalizer()
    try:
        await _run_services(services, runtime_state=runtime_context.runtime_state, tracker=tracker)
    finally:
        await _finalize_pipeline(
            finalizer=finalizer,
            context=context,
            resolved=resolved,
            summary=summary,
            runtime_context=runtime_context,
            sessions=sessions,
            channel=channel,
        )
    _attach_runtime_summary(summary, runtime_context.runtime_state)
    return _build_pipeline_run_result(summary, summary_file=resolved.summary_path)


async def _process_task(
    extractor: DetailPageWorker,
    task: URLTask,
    run_records: dict[str, dict],
    summary_lock: asyncio.Lock,
    state: PipelineRuntimeState | None = None,
    tracker: TaskProgressTracker | None = None,
    execution_id: str = "",
) -> None:
    await _process_task_impl(
        extractor=extractor,
        task=task,
        run_records=run_records,
        summary_lock=summary_lock,
        state=state,
        tracker=tracker,
        execution_id=execution_id,
        finalize_task_from_record=_finalize_task_from_record,
        claim_persisted_item=_claim_persisted_item,
        commit_persisted_item=_commit_persisted_item,
        fail_persisted_item=_fail_persisted_item,
        ack_persisted_item=_ack_persisted_item,
        release_persisted_claim=_release_persisted_claim,
        classify_runtime_exception=classify_runtime_exception,
        set_state_error_fn=_set_state_error,
    )

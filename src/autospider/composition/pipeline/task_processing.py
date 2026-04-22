"""Task-level pipeline runtime helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from autospider.contexts.collection.infrastructure.channel.base import URLTask
from autospider.platform.browser.intervention import BrowserInterventionRequired

from .extraction_state import build_error_reason, build_item_payload, record_extraction_evidence
from .orchestration import PipelineRuntimeState
from .progress_tracker import TaskProgressTracker
from .task_records import (
    build_worker_id,
    handle_existing_record,
    normalize_task_url,
    read_run_record,
    remove_run_record,
    track_final_record,
    write_run_record,
)

FinalizeTaskFromRecord = Callable[[URLTask, dict[str, Any]], Awaitable[None]]
PersistedItemOperation = Callable[..., Awaitable[dict[str, Any]]]
RuntimeExceptionClassifier = Callable[..., dict[str, Any]]


def set_state_error(state: PipelineRuntimeState, error: str) -> None:
    if not state.error:
        state.error = error


async def _restore_single_record(
    tracker: TaskProgressTracker,
    record: dict[str, Any],
) -> None:
    if str(record.get("durability_state") or "").strip().lower() != "durable":
        return
    url = str(record.get("url") or "").strip()
    if record.get("success"):
        await tracker.record_success(url)
        return
    if record.get("success") is False:
        await tracker.record_failure(url, str(record.get("failure_reason") or ""))


async def restore_resume_tracker_progress(
    tracker: TaskProgressTracker,
    records: dict[str, dict[str, Any]],
    *,
    build_record_summary: Callable[[dict[str, dict[str, Any]]], dict[str, int]],
) -> None:
    if not records:
        return
    record_summary = build_record_summary(records)
    total_urls = int(record_summary.get("total_urls", 0) or 0)
    if total_urls > 0:
        await tracker.set_total(total_urls)
    for record in records.values():
        await _restore_single_record(tracker, record)


async def _claim_run_record(
    *,
    task: URLTask,
    url: str,
    worker_id: str,
    execution_id: str,
    run_records: dict[str, dict[str, Any]],
    summary_lock: asyncio.Lock,
    claim_persisted_item: PersistedItemOperation,
) -> bool:
    try:
        claimed_record = await claim_persisted_item(
            execution_id=execution_id,
            url=url,
            worker_id=worker_id,
        )
    except RuntimeError as exc:
        if str(exc) == "duplicate_inflight_claim":
            await task.fail_task("duplicate_inflight_claim")
            return False
        raise
    await write_run_record(run_records, summary_lock, url=url, run_record=claimed_record)
    return True


async def _handle_browser_intervention(
    *,
    task: URLTask,
    url: str,
    worker_id: str,
    execution_id: str,
    run_records: dict[str, dict[str, Any]],
    summary_lock: asyncio.Lock,
    state: PipelineRuntimeState | None,
    tracker: TaskProgressTracker | None,
    release_persisted_claim: PersistedItemOperation,
) -> None:
    if state is not None:
        state.terminal_reason = "browser_intervention"
    if tracker is not None:
        await tracker.set_runtime_state(
            {
                "stage": "interrupted",
                "terminal_reason": "browser_intervention",
            }
        )
    await release_persisted_claim(
        execution_id=execution_id,
        url=url,
        worker_id=worker_id,
        terminal_reason="browser_intervention_released_claim",
    )
    await task.release_task("browser_intervention")
    await remove_run_record(run_records, summary_lock, url=url)


def _apply_runtime_exception(
    state: PipelineRuntimeState | None,
    *,
    error: Exception,
    url: str,
    classify_runtime_exception: RuntimeExceptionClassifier,
    set_state_error_fn: Callable[[PipelineRuntimeState, str], None],
) -> None:
    if state is None:
        return
    set_state_error_fn(state, f"extractor_system_error: {error}")
    state.terminal_reason = "extractor_system_error"
    if state.failure_category:
        return
    classified = classify_runtime_exception(
        component="pipeline.extractor",
        error=error,
        page_id=url,
    )
    state.failure_category = str(classified.get("category") or "")
    state.failure_detail = str(classified.get("detail") or str(error) or "")


async def _fail_for_exception(
    *,
    error: Exception,
    url: str,
    worker_id: str,
    execution_id: str,
    state: PipelineRuntimeState | None,
    classify_runtime_exception: RuntimeExceptionClassifier,
    set_state_error_fn: Callable[[PipelineRuntimeState, str], None],
    fail_persisted_item: PersistedItemOperation,
) -> dict[str, Any]:
    _apply_runtime_exception(
        state,
        error=error,
        url=url,
        classify_runtime_exception=classify_runtime_exception,
        set_state_error_fn=set_state_error_fn,
    )
    return await fail_persisted_item(
        execution_id=execution_id,
        url=url,
        failure_reason=f"extractor_exception: {error}",
        item={"url": url, "_error": f"extractor_exception: {error}"},
        worker_id=worker_id,
        terminal_reason="extractor_system_error",
        error_kind="system_failure",
    )
async def _persist_worker_result(
    *,
    worker_result: Any,
    url: str,
    worker_id: str,
    execution_id: str,
    state: PipelineRuntimeState | None,
    commit_persisted_item: PersistedItemOperation,
    fail_persisted_item: PersistedItemOperation,
) -> dict[str, Any]:
    record = worker_result.record
    record_extraction_evidence(
        state,
        url=url,
        extraction_config=dict(worker_result.extraction_config or {}),
        success=bool(record.success),
    )
    item = build_item_payload(record)
    if record.success:
        return await commit_persisted_item(
            execution_id=execution_id,
            url=url,
            item=item,
            worker_id=worker_id,
        )
    return await fail_persisted_item(
        execution_id=execution_id,
        url=url,
        failure_reason=build_error_reason(record),
        item=item,
        worker_id=worker_id,
        terminal_reason="field_extraction_failed",
        error_kind="business_failure",
    )


async def _ack_or_fail_task(
    *,
    task: URLTask,
    url: str,
    execution_id: str,
    run_record: dict[str, Any],
    ack_persisted_item: PersistedItemOperation,
) -> dict[str, Any]:
    if run_record.get("success"):
        await task.ack_task()
        return await ack_persisted_item(execution_id=execution_id, url=url)
    await task.fail_task(str(run_record.get("failure_reason") or "extraction_failed"))
    return run_record


async def process_task(
    *,
    extractor: Any,
    task: URLTask,
    run_records: dict[str, dict[str, Any]],
    summary_lock: asyncio.Lock,
    state: PipelineRuntimeState | None = None,
    tracker: TaskProgressTracker | None = None,
    execution_id: str = "",
    finalize_task_from_record: FinalizeTaskFromRecord,
    claim_persisted_item: PersistedItemOperation,
    commit_persisted_item: PersistedItemOperation,
    fail_persisted_item: PersistedItemOperation,
    ack_persisted_item: PersistedItemOperation,
    release_persisted_claim: PersistedItemOperation,
    classify_runtime_exception: RuntimeExceptionClassifier,
    set_state_error_fn: Callable[[PipelineRuntimeState, str], None],
) -> None:
    url = normalize_task_url(task)
    if not url:
        await task.fail_task("empty_url")
        return
    worker_id = build_worker_id(execution_id)
    existing_record = await read_run_record(run_records, summary_lock, url=url)
    if await handle_existing_record(
        task,
        existing_record,
        tracker=tracker,
        finalize_task_from_record=finalize_task_from_record,
    ):
        return
    if not await _claim_run_record(
        task=task,
        url=url,
        worker_id=worker_id,
        execution_id=execution_id,
        run_records=run_records,
        summary_lock=summary_lock,
        claim_persisted_item=claim_persisted_item,
    ):
        return
    try:
        worker_result = await extractor.extract(url)
    except BrowserInterventionRequired:
        await _handle_browser_intervention(
            task=task,
            url=url,
            worker_id=worker_id,
            execution_id=execution_id,
            run_records=run_records,
            summary_lock=summary_lock,
            state=state,
            tracker=tracker,
            release_persisted_claim=release_persisted_claim,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        run_record = await _fail_for_exception(
            error=exc,
            url=url,
            worker_id=worker_id,
            execution_id=execution_id,
            state=state,
            classify_runtime_exception=classify_runtime_exception,
            set_state_error_fn=set_state_error_fn,
            fail_persisted_item=fail_persisted_item,
        )
    else:
        run_record = await _persist_worker_result(
            worker_result=worker_result,
            url=url,
            worker_id=worker_id,
            execution_id=execution_id,
            state=state,
            commit_persisted_item=commit_persisted_item,
            fail_persisted_item=fail_persisted_item,
        )
    await write_run_record(run_records, summary_lock, url=url, run_record=run_record)
    final_record = await _ack_or_fail_task(
        task=task,
        url=url,
        execution_id=execution_id,
        run_record=run_record,
        ack_persisted_item=ack_persisted_item,
    )
    await write_run_record(run_records, summary_lock, url=url, run_record=final_record)
    await track_final_record(tracker, url=url, run_record=final_record)

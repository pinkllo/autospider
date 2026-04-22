"""Run-record state helpers for task-level processing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from autospider.contexts.collection.infrastructure.channel.base import URLTask

from .progress_tracker import TaskProgressTracker

FinalizeTaskFromRecord = Callable[[URLTask, dict[str, Any]], Awaitable[None]]


def _is_finalized_run_record(record: dict[str, Any] | None) -> bool:
    if not isinstance(record, dict):
        return False
    claim_state = str(record.get("claim_state") or "").strip().lower()
    durability_state = str(record.get("durability_state") or "").strip().lower()
    return durability_state == "durable" or claim_state in {"committed", "acked", "failed"}


def normalize_task_url(task: URLTask) -> str:
    return str(task.url or "").strip()


def build_worker_id(execution_id: str) -> str:
    return f"{execution_id}:{id(asyncio.current_task())}"


async def read_run_record(
    run_records: dict[str, dict[str, Any]],
    summary_lock: asyncio.Lock,
    *,
    url: str,
) -> dict[str, Any] | None:
    async with summary_lock:
        return run_records.get(url)


async def write_run_record(
    run_records: dict[str, dict[str, Any]],
    summary_lock: asyncio.Lock,
    *,
    url: str,
    run_record: dict[str, Any],
) -> None:
    async with summary_lock:
        run_records[url] = run_record


async def remove_run_record(
    run_records: dict[str, dict[str, Any]],
    summary_lock: asyncio.Lock,
    *,
    url: str,
) -> None:
    async with summary_lock:
        run_records.pop(url, None)


async def _track_existing_record(
    tracker: TaskProgressTracker | None,
    record: dict[str, Any],
) -> None:
    if tracker is None:
        return
    url = str(record.get("url") or "").strip()
    if record.get("success") and record.get("durability_state") == "durable":
        await tracker.record_success(url)
        return
    if not record.get("success"):
        await tracker.record_failure(url, str(record.get("failure_reason") or ""))


async def handle_existing_record(
    task: URLTask,
    existing_record: dict[str, Any] | None,
    *,
    tracker: TaskProgressTracker | None,
    finalize_task_from_record: FinalizeTaskFromRecord,
) -> bool:
    if not _is_finalized_run_record(existing_record):
        return False
    assert existing_record is not None
    if str(existing_record.get("claim_state") or "") == "claimed":
        await task.fail_task("duplicate_inflight_claim")
        return True
    await finalize_task_from_record(task, existing_record)
    await _track_existing_record(tracker, existing_record)
    return True


async def track_final_record(
    tracker: TaskProgressTracker | None,
    *,
    url: str,
    run_record: dict[str, Any],
) -> None:
    if tracker is None:
        return
    if run_record.get("success"):
        await tracker.record_success(url)
        return
    await tracker.record_failure(url, str(run_record.get("failure_reason") or ""))

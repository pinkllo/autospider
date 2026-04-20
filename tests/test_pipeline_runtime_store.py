from __future__ import annotations

import importlib
from typing import Any

import pytest

from autospider.legacy.pipeline.progress_tracker import TaskProgressTracker


class _FakeRedisClient:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.expire_calls: list[tuple[str, int]] = []

    def hset(self, key: str, mapping: dict[str, Any]) -> None:
        bucket = self.hashes.setdefault(key, {})
        for field, value in mapping.items():
            bucket[str(field)] = str(value)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def expire(self, key: str, ttl_s: int) -> None:
        self.expire_calls.append((key, ttl_s))


def _load_runtime_store_module():
    try:
        return importlib.import_module("autospider.legacy.common.storage.pipeline_runtime_store")
    except ModuleNotFoundError as exc:
        pytest.fail(f"pipeline runtime store module missing: {exc}")


def test_pipeline_runtime_store_round_trips_rich_runtime_state() -> None:
    runtime_store_module = _load_runtime_store_module()
    store_cls = getattr(runtime_store_module, "PipelineRuntimeStore", None)
    assert callable(store_cls)

    client = _FakeRedisClient()
    store = store_cls(client_factory=lambda: client)
    state = {
        "execution_id": "run-1",
        "status": "running",
        "completed": 2,
        "failed": 1,
        "total": 5,
        "progress": "3/5",
        "runtime_state": {
            "stage": "resume_backfilled",
            "queue": {"pending_count": 2, "stream_length": 7},
        },
    }

    store.save_runtime_state("run-1", state, ttl_s=90)

    assert store.get_runtime_state("run-1") == state
    assert client.expire_calls == [("autospider:task_progress:run-1", 90)]


def test_pipeline_runtime_store_round_trips_canonical_runtime_fields() -> None:
    runtime_store_module = _load_runtime_store_module()
    store_cls = getattr(runtime_store_module, "PipelineRuntimeStore", None)
    assert callable(store_cls)

    client = _FakeRedisClient()
    store = store_cls(client_factory=lambda: client)
    state = {
        "execution_id": "run-canonical",
        "status": "running",
        "stage": "collecting",
        "resume_mode": "resume",
        "thread_id": "thread-7",
        "completed": 2,
        "failed": 1,
        "total": 5,
        "current_url": "https://example.com/item-3",
        "last_error": "field_missing",
        "released_claims": 4,
        "recovered_pending": 2,
        "stream_length": 9,
        "pending_count": 3,
        "updated_at": 1710000000,
        "finished_at": 1710000042,
    }

    store.save_runtime_state("run-canonical", state)

    assert store.get_runtime_state("run-canonical") == state


def test_pipeline_runtime_store_reads_legacy_progress_hash_without_payload() -> None:
    runtime_store_module = _load_runtime_store_module()
    store_cls = getattr(runtime_store_module, "PipelineRuntimeStore", None)
    assert callable(store_cls)

    client = _FakeRedisClient()
    client.hashes["autospider:task_progress:legacy-run"] = {
        "status": "running",
        "completed": "3",
        "failed": "1",
        "total": "6",
        "progress": "4/6",
    }
    store = store_cls(client_factory=lambda: client)

    assert store.get_runtime_state("legacy-run") == {
        "status": "running",
        "completed": 3,
        "failed": 1,
        "total": 6,
        "progress": "4/6",
    }


def test_pipeline_runtime_store_reads_canonical_fields_from_legacy_hash_without_payload() -> None:
    runtime_store_module = _load_runtime_store_module()
    store_cls = getattr(runtime_store_module, "PipelineRuntimeStore", None)
    assert callable(store_cls)

    client = _FakeRedisClient()
    client.hashes["autospider:task_progress:legacy-canonical"] = {
        "status": "running",
        "stage": "consuming",
        "resume_mode": "resume",
        "thread_id": "thread-9",
        "completed": "3",
        "failed": "1",
        "total": "8",
        "current_url": "https://example.com/item-4",
        "last_error": "timeout",
        "released_claims": "5",
        "recovered_pending": "2",
        "stream_length": "11",
        "pending_count": "4",
        "updated_at": "1710000100",
        "finished_at": "1710000200",
    }
    store = store_cls(client_factory=lambda: client)

    assert store.get_runtime_state("legacy-canonical") == {
        "status": "running",
        "stage": "consuming",
        "resume_mode": "resume",
        "thread_id": "thread-9",
        "completed": 3,
        "failed": 1,
        "total": 8,
        "current_url": "https://example.com/item-4",
        "last_error": "timeout",
        "released_claims": 5,
        "recovered_pending": 2,
        "stream_length": 11,
        "pending_count": 4,
        "updated_at": 1710000100,
        "finished_at": 1710000200,
    }


@pytest.mark.asyncio
async def test_progress_tracker_persists_richer_runtime_state() -> None:
    runtime_store_module = _load_runtime_store_module()
    store_cls = getattr(runtime_store_module, "PipelineRuntimeStore", None)
    assert callable(store_cls)

    client = _FakeRedisClient()
    runtime_store = store_cls(client_factory=lambda: client)
    try:
        tracker = TaskProgressTracker("run-2", runtime_store=runtime_store)
    except TypeError as exc:
        pytest.fail(f"TaskProgressTracker should accept runtime_store injection: {exc}")

    set_runtime_state = getattr(tracker, "set_runtime_state", None)
    assert callable(set_runtime_state)

    await tracker.set_total(5)
    await tracker.record_success("https://example.com/item-1")
    await tracker.set_runtime_state(
        {
            "stage": "resume_backfilled",
            "queue": {"pending_count": 2, "stream_length": 7},
        }
    )

    state = runtime_store.get_runtime_state("run-2")
    assert isinstance(state, dict)
    assert isinstance(state.get("updated_at"), int)
    state.pop("updated_at", None)

    assert state == {
        "execution_id": "run-2",
        "status": "running",
        "stage": "resume_backfilled",
        "completed": 1,
        "failed": 0,
        "total": 5,
        "progress": "1/5",
        "current_url": "https://example.com/item-1",
        "stream_length": 7,
        "pending_count": 2,
        "runtime_state": {
            "stage": "resume_backfilled",
            "queue": {"pending_count": 2, "stream_length": 7},
        },
    }


@pytest.mark.asyncio
async def test_progress_tracker_promotes_canonical_runtime_fields_to_top_level() -> None:
    runtime_store_module = _load_runtime_store_module()
    store_cls = getattr(runtime_store_module, "PipelineRuntimeStore", None)
    assert callable(store_cls)

    client = _FakeRedisClient()
    runtime_store = store_cls(client_factory=lambda: client)
    tracker = TaskProgressTracker("run-3", runtime_store=runtime_store)

    await tracker.set_total(6)
    await tracker.record_success("https://example.com/item-1")
    await tracker.record_failure("https://example.com/item-2", "timeout")
    await tracker.set_runtime_state(
        {
            "stage": "consuming",
            "resume_mode": "resume",
            "thread_id": "thread-3",
            "released_claims": 5,
            "recovered_pending": 2,
            "stream_length": 11,
            "pending_count": 4,
        }
    )

    state = runtime_store.get_runtime_state("run-3")
    assert isinstance(state, dict)
    assert state["status"] == "running"
    assert state["stage"] == "consuming"
    assert state["resume_mode"] == "resume"
    assert state["thread_id"] == "thread-3"
    assert state["completed"] == 1
    assert state["failed"] == 1
    assert state["total"] == 6
    assert state["current_url"] == "https://example.com/item-2"
    assert state["last_error"] == "timeout"
    assert state["released_claims"] == 5
    assert state["recovered_pending"] == 2
    assert state["stream_length"] == 11
    assert state["pending_count"] == 4
    assert isinstance(state["updated_at"], int)


@pytest.mark.asyncio
async def test_progress_tracker_mark_done_preserves_canonical_fields_and_finished_at() -> None:
    runtime_store_module = _load_runtime_store_module()
    store_cls = getattr(runtime_store_module, "PipelineRuntimeStore", None)
    assert callable(store_cls)

    client = _FakeRedisClient()
    runtime_store = store_cls(client_factory=lambda: client)
    tracker = TaskProgressTracker("run-4", runtime_store=runtime_store)

    await tracker.set_total(2)
    await tracker.record_success("https://example.com/item-1")
    await tracker.set_runtime_state(
        {"stage": "consuming", "resume_mode": "resume", "thread_id": "thread-4"}
    )
    await tracker.mark_done("completed")

    state = runtime_store.get_runtime_state("run-4")
    assert isinstance(state, dict)
    assert state["status"] == "completed"
    assert state["stage"] == "consuming"
    assert state["resume_mode"] == "resume"
    assert state["thread_id"] == "thread-4"
    assert state["completed"] == 1
    assert state["failed"] == 0
    assert state["total"] == 2
    assert isinstance(state["updated_at"], int)
    assert isinstance(state["finished_at"], int)
    assert client.expire_calls[-1] == ("autospider:task_progress:run-4", 600)

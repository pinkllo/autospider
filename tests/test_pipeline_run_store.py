from __future__ import annotations

import pytest

from autospider.domain.fields import FieldDefinition
from autospider.pipeline import run_store, run_store_async, runner
from autospider.pipeline.types import PipelineMode, TaskIdentity


def test_release_inflight_items_for_resume_returns_zero_without_execution_id() -> None:
    assert run_store._release_inflight_items_for_resume("") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("async_name", "sync_name", "kwargs", "expected"),
    [
        (
            "_release_inflight_items_for_resume",
            "_release_inflight_items_for_resume",
            {"execution_id": "exec-1"},
            2,
        ),
        (
            "_claim_persisted_item",
            "_claim_persisted_item",
            {"execution_id": "exec-1", "url": "https://example.com/item-1", "worker_id": "worker-1"},
            {"claim_state": "claimed"},
        ),
        (
            "_commit_persisted_item",
            "_commit_persisted_item",
            {
                "execution_id": "exec-1",
                "url": "https://example.com/item-1",
                "item": {"url": "https://example.com/item-1"},
                "worker_id": "worker-1",
            },
            {"claim_state": "committed"},
        ),
        (
            "_fail_persisted_item",
            "_fail_persisted_item",
            {
                "execution_id": "exec-1",
                "url": "https://example.com/item-1",
                "failure_reason": "boom",
                "item": {"url": "https://example.com/item-1"},
                "worker_id": "worker-1",
                "terminal_reason": "extractor_system_error",
                "error_kind": "system_failure",
            },
            {"claim_state": "failed"},
        ),
        (
            "_ack_persisted_item",
            "_ack_persisted_item",
            {"execution_id": "exec-1", "url": "https://example.com/item-1"},
            {"claim_state": "acked"},
        ),
        (
            "_release_persisted_claim",
            "_release_persisted_claim",
            {
                "execution_id": "exec-1",
                "url": "https://example.com/item-1",
                "worker_id": "worker-1",
                "terminal_reason": "browser_intervention_released_claim",
            },
            {"claim_state": "pending"},
        ),
        (
            "_persist_run_snapshot",
            "_persist_run_snapshot",
            {
                "identity": TaskIdentity(
                    list_url="https://example.com/list",
                    task_description="collect items",
                ),
                "fields": [FieldDefinition(name="title", description="Title")],
                "execution_id": "exec-1",
                "thread_id": "thread-1",
                "output_dir": "artifacts/test-output",
                "pipeline_mode": PipelineMode.REDIS,
                "summary": {"execution_state": "running"},
            },
            None,
        ),
    ],
)
async def test_async_run_store_bridges_sync_helpers_via_to_thread(
    monkeypatch: pytest.MonkeyPatch,
    async_name: str,
    sync_name: str,
    kwargs: dict,
    expected: object,
) -> None:
    observed: list[tuple[object, dict]] = []

    def fake_sync(**actual_kwargs: object) -> object:
        observed.append(("sync", dict(actual_kwargs)))
        return expected

    async def fake_to_thread(func: object, /, *args: object, **actual_kwargs: object) -> object:
        observed.append((func, dict(actual_kwargs)))
        assert args == ()
        return func(**actual_kwargs)

    monkeypatch.setattr(run_store, sync_name, fake_sync)
    monkeypatch.setattr(run_store_async.asyncio, "to_thread", fake_to_thread)

    actual = await getattr(run_store_async, async_name)(**kwargs)

    assert actual == expected
    assert observed == [
        (fake_sync, kwargs),
        ("sync", kwargs),
    ]


def test_runner_uses_async_run_store_persistence_helpers() -> None:
    assert runner._claim_persisted_item is run_store_async._claim_persisted_item
    assert runner._commit_persisted_item is run_store_async._commit_persisted_item
    assert runner._fail_persisted_item is run_store_async._fail_persisted_item
    assert runner._ack_persisted_item is run_store_async._ack_persisted_item
    assert runner._release_persisted_claim is run_store_async._release_persisted_claim
    assert runner._release_inflight_items_for_resume is run_store_async._release_inflight_items_for_resume
    assert runner._persist_run_snapshot is run_store_async._persist_run_snapshot

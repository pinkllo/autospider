from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from autospider.platform.browser.intervention import BrowserInterventionRequired
from autospider.contexts.collection.infrastructure.channel.base import URLTask
from autospider.platform.persistence.sql.orm.models import Base
from autospider.platform.persistence.sql.orm.repositories import (
    TaskRunPayload,
    TaskRunReadRepository,
    TaskRunWriteRepository,
)
from autospider.composition.pipeline import runner


def test_runner_persistence_helpers_are_async() -> None:
    assert inspect.iscoroutinefunction(runner._persist_run_snapshot)
    assert inspect.iscoroutinefunction(runner._claim_persisted_item)
    assert inspect.iscoroutinefunction(runner._commit_persisted_item)
    assert inspect.iscoroutinefunction(runner._fail_persisted_item)
    assert inspect.iscoroutinefunction(runner._ack_persisted_item)


class _InterventionExtractor:
    async def extract(self, url: str) -> object:
        raise BrowserInterventionRequired({"message": f"captcha at {url}"})


class _TrackerStub:
    def __init__(self) -> None:
        self.runtime_state_calls: list[dict[str, str]] = []
        self.success_calls: list[str] = []
        self.failure_calls: list[tuple[str, str]] = []

    async def set_runtime_state(self, payload: dict[str, str]) -> None:
        self.runtime_state_calls.append(dict(payload))

    async def record_success(self, url: str = "") -> None:
        self.success_calls.append(url)

    async def record_failure(self, url: str = "", error: str = "") -> None:
        self.failure_calls.append((url, error))


def _build_repo_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _build_run_payload(execution_id: str) -> TaskRunPayload:
    return TaskRunPayload(
        normalized_url="https://example.com/list",
        original_url="https://example.com/list",
        task_description="collect items",
        field_names=["title"],
        execution_id=execution_id,
        output_dir="output/test",
        pipeline_mode="memory",
    )


@pytest.mark.asyncio
async def test_process_task_releases_persisted_claim_after_browser_intervention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed_record = {
        "url": "https://example.com/item-1",
        "claim_state": "claimed",
        "durability_state": "staged",
        "worker_id": "worker-1",
    }
    released_calls: list[dict[str, str]] = []
    requeued: list[str] = []
    acked: list[str] = []
    failed: list[str] = []

    async def fake_claim_persisted_item(**_: str) -> dict[str, str]:
        return dict(claimed_record)

    async def fake_release_persisted_claim(**kwargs: str) -> dict[str, str]:
        released_calls.append(dict(kwargs))
        return {
            "url": kwargs["url"],
            "claim_state": "pending",
            "durability_state": "staged",
            "worker_id": "",
            "terminal_reason": kwargs["terminal_reason"],
        }

    async def ack_task() -> None:
        acked.append("acked")

    async def fail_task(reason: str) -> None:
        failed.append(reason)

    async def release_task(reason: str) -> None:
        requeued.append(reason)

    monkeypatch.setattr(runner, "_claim_persisted_item", fake_claim_persisted_item)
    monkeypatch.setattr(
        runner, "_release_persisted_claim", fake_release_persisted_claim, raising=False
    )

    tracker = _TrackerStub()
    run_records: dict[str, dict] = {}
    task = URLTask(
        url="https://example.com/item-1",
        ack=ack_task,
        fail=fail_task,
        release=release_task,
    )

    with pytest.raises(BrowserInterventionRequired):
        await runner._process_task(
            extractor=_InterventionExtractor(),
            task=task,
            run_records=run_records,
            summary_lock=asyncio.Lock(),
            tracker=tracker,
            execution_id="exec-123",
        )

    assert released_calls == [
        {
            "execution_id": "exec-123",
            "url": "https://example.com/item-1",
            "worker_id": ANY,
            "terminal_reason": "browser_intervention_released_claim",
        }
    ]
    assert isinstance(released_calls[0]["worker_id"], str)
    assert released_calls[0]["worker_id"].startswith("exec-123:")
    assert run_records == {}
    assert requeued == ["browser_intervention"]
    assert acked == []
    assert failed == []
    assert tracker.runtime_state_calls == [
        {"stage": "interrupted", "terminal_reason": "browser_intervention"}
    ]


class _SuccessfulExtractor:
    async def extract(self, url: str) -> object:
        record = SimpleNamespace(
            url=url,
            success=True,
            fields=[SimpleNamespace(field_name="title", value="Title 1", error="")],
        )
        return SimpleNamespace(record=record, extraction_config={"fields": [{"name": "title"}]})


class _BusinessFailureExtractor:
    async def extract(self, url: str) -> object:
        record = SimpleNamespace(
            url=url,
            success=False,
            fields=[SimpleNamespace(field_name="title", value="", error="missing_title")],
        )
        return SimpleNamespace(record=record, extraction_config={"fields": [{"name": "title"}]})


@pytest.mark.asyncio
async def test_process_task_awaits_async_commit_and_ack_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed_record = {
        "url": "https://example.com/item-success",
        "claim_state": "claimed",
        "durability_state": "staged",
    }
    commit_calls: list[dict[str, str | dict[str, str]]] = []
    ack_calls: list[dict[str, str]] = []
    acked: list[str] = []
    tracker = _TrackerStub()
    run_records: dict[str, dict] = {}

    async def fake_claim_persisted_item(**_: str) -> dict[str, str]:
        return dict(claimed_record)

    async def fake_commit_persisted_item(**kwargs: str | dict[str, str]) -> dict[str, str]:
        commit_calls.append(dict(kwargs))
        return {
            "url": str(kwargs["url"]),
            "success": True,
            "claim_state": "committed",
            "durability_state": "durable",
            "worker_id": str(kwargs["worker_id"]),
        }

    async def fake_ack_persisted_item(**kwargs: str) -> dict[str, str]:
        ack_calls.append(dict(kwargs))
        return {
            "url": kwargs["url"],
            "success": True,
            "claim_state": "acked",
            "durability_state": "durable",
        }

    async def ack_task() -> None:
        acked.append("acked")

    monkeypatch.setattr(runner, "_claim_persisted_item", fake_claim_persisted_item)
    monkeypatch.setattr(runner, "_commit_persisted_item", fake_commit_persisted_item)
    monkeypatch.setattr(runner, "_ack_persisted_item", fake_ack_persisted_item)

    task = URLTask(url="https://example.com/item-success", ack=ack_task)

    await runner._process_task(
        extractor=_SuccessfulExtractor(),
        task=task,
        run_records=run_records,
        summary_lock=asyncio.Lock(),
        tracker=tracker,
        execution_id="exec-123",
    )

    assert commit_calls == [
        {
            "execution_id": "exec-123",
            "url": "https://example.com/item-success",
            "item": {"url": "https://example.com/item-success", "title": "Title 1"},
            "worker_id": ANY,
        }
    ]
    assert ack_calls == [{"execution_id": "exec-123", "url": "https://example.com/item-success"}]
    assert acked == ["acked"]
    assert run_records["https://example.com/item-success"]["claim_state"] == "acked"
    assert tracker.success_calls == ["https://example.com/item-success"]
    assert tracker.failure_calls == []


@pytest.mark.asyncio
async def test_process_task_awaits_async_fail_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed: list[str] = []
    fail_calls: list[dict[str, str | dict[str, str]]] = []
    tracker = _TrackerStub()
    run_records: dict[str, dict] = {}

    async def fake_claim_persisted_item(**_: str) -> dict[str, str]:
        return {
            "url": "https://example.com/item-failure",
            "claim_state": "claimed",
            "durability_state": "staged",
        }

    async def fake_fail_persisted_item(**kwargs: str | dict[str, str]) -> dict[str, str]:
        fail_calls.append(dict(kwargs))
        return {
            "url": str(kwargs["url"]),
            "success": False,
            "failure_reason": str(kwargs["failure_reason"]),
            "claim_state": "failed",
            "durability_state": "durable",
        }

    async def fail_task(reason: str) -> None:
        failed.append(reason)

    monkeypatch.setattr(runner, "_claim_persisted_item", fake_claim_persisted_item)
    monkeypatch.setattr(runner, "_fail_persisted_item", fake_fail_persisted_item)

    task = URLTask(url="https://example.com/item-failure", fail=fail_task)

    await runner._process_task(
        extractor=_BusinessFailureExtractor(),
        task=task,
        run_records=run_records,
        summary_lock=asyncio.Lock(),
        tracker=tracker,
        execution_id="exec-123",
    )

    assert fail_calls == [
        {
            "execution_id": "exec-123",
            "url": "https://example.com/item-failure",
            "failure_reason": "missing_title",
            "item": {"url": "https://example.com/item-failure", "title": ""},
            "worker_id": ANY,
            "terminal_reason": "field_extraction_failed",
            "error_kind": "business_failure",
        }
    ]
    assert failed == ["missing_title"]
    assert run_records["https://example.com/item-failure"]["claim_state"] == "failed"
    assert tracker.success_calls == []
    assert tracker.failure_calls == [("https://example.com/item-failure", "missing_title")]


def test_release_claimed_item_resets_inflight_state() -> None:
    session = _build_repo_session()
    try:
        repo = TaskRunWriteRepository(session)
        execution_id = "exec-claim-release"
        url = "https://example.com/item-2"
        repo.save_run(_build_run_payload(execution_id))
        repo.claim_item(
            execution_id=execution_id,
            url=url,
            worker_id="worker-1",
            item_data={"url": url},
        )

        released = repo.release_claimed_item(
            execution_id=execution_id,
            url=url,
            worker_id="worker-1",
            terminal_reason="browser_intervention_released_claim",
        )

        assert released["claim_state"] == "pending"
        assert released["durability_state"] == "staged"
        assert released["terminal_reason"] == "browser_intervention_released_claim"
        assert released["worker_id"] == ""
        assert released["attempt_count"] == 1

        persisted = TaskRunReadRepository(session).get_item(execution_id, url)
        assert persisted is not None
        assert persisted["claim_state"] == "pending"
        assert persisted["durability_state"] == "staged"
        assert persisted["worker_id"] == ""
    finally:
        session.close()


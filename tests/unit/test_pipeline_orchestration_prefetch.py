from __future__ import annotations

import asyncio

import pytest

from autospider.common.channel.base import URLTask
from autospider.pipeline.orchestration import (
    ConsumerPool,
    PipelineRuntimeContext,
    PipelineRuntimeDependencies,
    PipelineSessionBundle,
    ProducerService,
)


class _FakePage:
    async def goto(self, *args, **kwargs):
        return None


class _FakeBrowserSession:
    def __init__(self, *args, **kwargs):
        self.page = _FakePage()
        self.stop_calls = 0

    async def start(self):
        return None

    async def stop(self):
        self.stop_calls += 1
        return None


class _NoopTracker:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id

    async def set_total(self, total: int):
        return None

    async def record_success(self, url: str = ""):
        return None

    async def record_failure(self, url: str = "", error: str = ""):
        return None

    async def mark_done(self, final_status: str = "completed"):
        return None


class _SingleFetchChannel:
    def __init__(self, urls: list[str]) -> None:
        self.urls = list(urls)
        self.fetch_calls: list[int] = []

    async def fetch(self, max_items: int, timeout_s: float | None):
        self.fetch_calls.append(max_items)
        if not self.urls:
            return []
        return [URLTask(url=self.urls.pop(0))]

    async def is_drained(self):
        return not self.urls


class _ExtractorStub:
    def __init__(self, *args, **kwargs):
        return None


class _SealOnlyChannel:
    def __init__(self) -> None:
        self.sealed = 0

    async def seal(self):
        self.sealed += 1


class _CollectorStub:
    def __init__(self, **kwargs):
        self.page = kwargs["page"]

    async def run(self):
        return type(
            "_Result",
            (),
            {
                "collected_urls": ["https://example.com/1"],
            },
        )()


@pytest.mark.asyncio
async def test_consumer_pool_limits_claims_to_available_worker_slots():
    channel = _SingleFetchChannel(["https://example.com/1", "https://example.com/2"])
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    started_urls: list[str] = []

    async def _process_task(**kwargs):
        task = kwargs["task"]
        started_urls.append(task.url)
        if len(started_urls) == 1:
            first_started.set()
            await release_first.wait()

    context = PipelineRuntimeContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect",
        execution_brief={},
        fields=[],
        output_dir="output",
        headless=True,
        explore_count=1,
        validate_count=1,
        consumer_workers=1,
        max_pages=1,
        target_url_count=2,
        guard_intervention_mode="auto",
        guard_thread_id="thread-1",
        selected_skills=None,
        channel=channel,
        redis_manager=None,
        run_records={},
        summary={},
        tracker=_NoopTracker("exec-1"),
        skill_runtime=object(),
        sessions=PipelineSessionBundle(list_session=_FakeBrowserSession()),
    )
    deps = PipelineRuntimeDependencies(
        browser_session_factory=_FakeBrowserSession,
        collector_cls=object,
        detail_page_worker_cls=_ExtractorStub,
        set_state_error=lambda state, reason: None,
        process_task=_process_task,
    )
    pool = ConsumerPool(context, deps)

    run_task = asyncio.create_task(pool.run())
    await first_started.wait()
    await asyncio.sleep(0.1)

    assert channel.fetch_calls == [1]

    release_first.set()
    await run_task

    assert started_urls == ["https://example.com/1", "https://example.com/2"]
    assert channel.fetch_calls[:2] == [1, 1]


@pytest.mark.asyncio
async def test_producer_releases_list_session_before_sealing_channel():
    list_session = _FakeBrowserSession()
    channel = _SealOnlyChannel()
    tracker = _NoopTracker("exec-2")
    totals: list[int] = []

    async def _set_total(total: int):
        totals.append(total)

    tracker.set_total = _set_total  # type: ignore[method-assign]

    context = PipelineRuntimeContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect",
        execution_brief={},
        fields=[],
        output_dir="output",
        headless=True,
        explore_count=1,
        validate_count=1,
        consumer_workers=1,
        max_pages=1,
        target_url_count=1,
        guard_intervention_mode="auto",
        guard_thread_id="thread-2",
        selected_skills=None,
        channel=channel,
        redis_manager=None,
        run_records={},
        summary={},
        tracker=tracker,
        skill_runtime=object(),
        sessions=PipelineSessionBundle(list_session=list_session),
    )
    deps = PipelineRuntimeDependencies(
        browser_session_factory=_FakeBrowserSession,
        collector_cls=_CollectorStub,
        detail_page_worker_cls=_ExtractorStub,
        set_state_error=lambda state, reason: None,
        process_task=lambda **kwargs: None,
    )

    producer = ProducerService(context, deps)
    await producer.run()

    assert list_session.stop_calls == 1
    assert totals == [1]
    assert channel.sealed == 1

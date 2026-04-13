from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from autospider.pipeline import orchestration, runner
from autospider.pipeline.types import ExecutionContext, ExecutionRequest, PipelineMode, ResumeMode, TaskIdentity


class _FakeTracker:
    def __init__(self) -> None:
        self.runtime_state_calls: list[dict[str, Any]] = []
        self.total = 0
        self.completed = 0
        self.failed = 0
        self.done_calls: list[str] = []

    async def set_runtime_state(self, payload: dict[str, Any]) -> None:
        self.runtime_state_calls.append(dict(payload))

    async def set_total(self, total: int) -> None:
        self.total = total

    async def record_success(self, url: str = "") -> None:
        self.completed += 1

    async def record_failure(self, url: str = "", error: str = "") -> None:
        self.failed += 1

    async def mark_done(self, status: str = "completed") -> None:
        self.done_calls.append(status)


class _FakeBrowserRuntimeSession:
    def __init__(self, **_: Any) -> None:
        self.page = object()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeChannel:
    def __init__(self) -> None:
        self.sealed = False
        self.closed = False
        self.error_reason = ""

    async def seal(self) -> None:
        self.sealed = True

    async def close(self) -> None:
        self.closed = True

    async def close_with_error(self, reason: str) -> None:
        self.error_reason = reason

    async def is_drained(self) -> bool:
        return True


@dataclass
class _FakeServices:
    producer: Any
    consumer_pool: Any


class _CompletedFinalizer:
    def __init__(self, _: Any) -> None:
        return None

    async def finalize(self, context: Any) -> None:
        context.summary["execution_state"] = "completed"
        await context.tracker.mark_done("completed")
        await context.sessions.stop()


def _build_context(output_dir: Path, *, resume_mode: ResumeMode = ResumeMode.FRESH) -> ExecutionContext:
    request = ExecutionRequest(
        list_url="https://example.com/list",
        task_description="collect items",
        output_dir=str(output_dir),
        execution_id="exec-1",
        resume_mode=resume_mode,
    )
    return ExecutionContext(
        request=request,
        identity=TaskIdentity(list_url=request.list_url, task_description=request.task_description),
        fields=(),
        pipeline_mode=PipelineMode.REDIS,
        consumer_concurrency=1,
        max_concurrent=1,
        global_browser_budget=1,
        resume_mode=resume_mode,
        execution_id="exec-1",
    )


@pytest.mark.asyncio
async def test_run_pipeline_writes_starting_runtime_state_before_services_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = _FakeTracker()
    observed: list[dict[str, Any]] = []
    persisted_snapshots: list[str] = []
    output_dir = Path("artifacts") / "test_tmp" / "pipeline-runtime-starting"

    monkeypatch.setattr(runner, "TaskProgressTracker", lambda execution_id: tracker)
    monkeypatch.setattr(runner, "BrowserRuntimeSession", _FakeBrowserRuntimeSession)
    monkeypatch.setattr(runner, "create_url_channel", lambda **_: _FakeChannel())
    monkeypatch.setattr(runner, "_prepare_pipeline_output", lambda **_: None)
    async def persist_run_snapshot(**kwargs: Any) -> None:
        persisted_snapshots.append(str(kwargs["execution_id"]))

    monkeypatch.setattr(runner, "_persist_run_snapshot", persist_run_snapshot)
    monkeypatch.setattr(runner, "_load_persisted_run_records", lambda execution_id: {})
    monkeypatch.setattr(runner, "_release_inflight_items_for_resume", lambda execution_id: 0)
    monkeypatch.setattr(runner, "PipelineFinalizer", _CompletedFinalizer)

    async def _noop() -> None:
        return None

    def fake_create_pipeline_services(context: Any, deps: Any) -> _FakeServices:
        observed.append(
            {
                "runtime_state_calls": list(context.tracker.runtime_state_calls),
                "completed": context.tracker.completed,
                "failed": context.tracker.failed,
                "total": context.tracker.total,
                "resume_mode": context.resume_mode,
            }
        )
        return _FakeServices(producer=SimpleNamespace(run=_noop), consumer_pool=SimpleNamespace(run=_noop))

    monkeypatch.setattr(runner, "create_pipeline_services", fake_create_pipeline_services)

    result = await runner.run_pipeline(_build_context(output_dir))

    assert observed == [
        {
            "runtime_state_calls": [{"stage": "starting", "resume_mode": "fresh"}],
            "completed": 0,
            "failed": 0,
            "total": 0,
            "resume_mode": "fresh",
        }
    ]
    assert tracker.done_calls == ["completed"]
    assert persisted_snapshots == ["exec-1"]
    assert result.summary.execution_state == "completed"


@pytest.mark.asyncio
async def test_run_pipeline_backfills_resume_counts_before_services_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = _FakeTracker()
    observed: list[dict[str, Any]] = []
    persisted_snapshots: list[str] = []
    released_runs: list[str] = []
    output_dir = Path("artifacts") / "test_tmp" / "pipeline-runtime-resume"
    persisted = {
        "https://example.com/item-1": {
            "url": "https://example.com/item-1",
            "success": True,
            "durability_state": "durable",
            "claim_state": "acked",
            "failure_reason": "",
        },
        "https://example.com/item-2": {
            "url": "https://example.com/item-2",
            "success": True,
            "durability_state": "durable",
            "claim_state": "acked",
            "failure_reason": "",
        },
        "https://example.com/item-3": {
            "url": "https://example.com/item-3",
            "success": False,
            "durability_state": "durable",
            "claim_state": "failed",
            "failure_reason": "field_missing",
        },
    }

    monkeypatch.setattr(runner, "TaskProgressTracker", lambda execution_id: tracker)
    monkeypatch.setattr(runner, "BrowserRuntimeSession", _FakeBrowserRuntimeSession)
    monkeypatch.setattr(runner, "create_url_channel", lambda **_: _FakeChannel())
    monkeypatch.setattr(runner, "_prepare_pipeline_output", lambda **_: None)
    async def persist_run_snapshot(**kwargs: Any) -> None:
        persisted_snapshots.append(str(kwargs["execution_id"]))

    monkeypatch.setattr(runner, "_load_persisted_run_records", lambda execution_id: dict(persisted))
    monkeypatch.setattr(runner, "_persist_run_snapshot", persist_run_snapshot)

    async def release_inflight_items_for_resume(execution_id: str) -> int:
        released_runs.append(execution_id)
        return 0

    monkeypatch.setattr(runner, "_release_inflight_items_for_resume", release_inflight_items_for_resume)
    monkeypatch.setattr(runner, "PipelineFinalizer", _CompletedFinalizer)

    async def _noop() -> None:
        return None

    def fake_create_pipeline_services(context: Any, deps: Any) -> _FakeServices:
        observed.append(
            {
                "runtime_state_calls": list(context.tracker.runtime_state_calls),
                "completed": context.tracker.completed,
                "failed": context.tracker.failed,
                "total": context.tracker.total,
                "resume_mode": context.resume_mode,
            }
        )
        return _FakeServices(producer=SimpleNamespace(run=_noop), consumer_pool=SimpleNamespace(run=_noop))

    monkeypatch.setattr(runner, "create_pipeline_services", fake_create_pipeline_services)

    await runner.run_pipeline(_build_context(output_dir, resume_mode=ResumeMode.RESUME))

    assert observed == [
        {
            "runtime_state_calls": [{"stage": "starting", "resume_mode": "resume"}],
            "completed": 2,
            "failed": 1,
            "total": 3,
            "resume_mode": "resume",
        }
    ]
    assert persisted_snapshots == ["exec-1"]
    assert released_runs == ["exec-1"]


@pytest.mark.asyncio
async def test_producer_service_sets_collecting_runtime_stage() -> None:
    tracker = _FakeTracker()
    sessions = orchestration.PipelineSessionBundle(list_session=SimpleNamespace(page=object(), stop=lambda: None))

    async def _list_stop() -> None:
        return None

    sessions.list_session.stop = _list_stop

    class _Collector:
        def __init__(self, **_: Any) -> None:
            self.nav_steps = []
            self.pagination_handler = None
            self.common_detail_xpath = None

        async def run(self) -> Any:
            return SimpleNamespace(collected_urls=["u1", "u2"])

    context = orchestration.PipelineRuntimeContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect items",
        execution_brief={},
        fields=[],
        output_dir="output",
        headless=True,
        explore_count=1,
        validate_count=1,
        consumer_workers=1,
        max_pages=1,
        target_url_count=2,
        guard_intervention_mode="interrupt",
        guard_thread_id="thread-1",
        selected_skills=[],
        channel=_FakeChannel(),
        run_records={},
        summary={},
        tracker=tracker,
        skill_runtime=SimpleNamespace(),
        sessions=sessions,
    )
    deps = orchestration.PipelineRuntimeDependencies(
        browser_session_factory=_FakeBrowserRuntimeSession,
        collector_cls=_Collector,
        detail_page_worker_cls=SimpleNamespace,
        set_state_error=lambda state, error: None,
        process_task=lambda **_: None,
    )

    await orchestration.ProducerService(context, deps).run()

    assert tracker.runtime_state_calls == [{"stage": "collecting"}]


@pytest.mark.asyncio
async def test_consumer_worker_sets_consuming_runtime_stage_on_first_task() -> None:
    tracker = _FakeTracker()
    context = orchestration.PipelineRuntimeContext(
        list_url="https://example.com/list",
        anchor_url=None,
        page_state_signature="sig",
        variant_label=None,
        task_description="collect items",
        execution_brief={},
        fields=[],
        output_dir="output",
        headless=True,
        explore_count=1,
        validate_count=1,
        consumer_workers=1,
        max_pages=1,
        target_url_count=2,
        guard_intervention_mode="interrupt",
        guard_thread_id="thread-1",
        selected_skills=[],
        channel=_FakeChannel(),
        run_records={},
        summary={},
        tracker=tracker,
        skill_runtime=SimpleNamespace(),
        sessions=orchestration.PipelineSessionBundle(list_session=SimpleNamespace()),
    )
    deps = orchestration.PipelineRuntimeDependencies(
        browser_session_factory=_FakeBrowserRuntimeSession,
        collector_cls=SimpleNamespace,
        detail_page_worker_cls=SimpleNamespace,
        set_state_error=lambda state, error: None,
        process_task=lambda **_: None,
    )
    pool = orchestration.ConsumerPool(context, deps)
    pool._claim_slots = SimpleNamespace(release=lambda: None)
    task_queue: Any = orchestration.asyncio.Queue()
    await task_queue.put(SimpleNamespace(url="https://example.com/item-1"))
    await task_queue.put(None)

    class _Session:
        def __init__(self, **_: Any) -> None:
            self.page = object()

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class _Extractor:
        def __init__(self, **_: Any) -> None:
            return None

    async def process_task(**_: Any) -> None:
        return None

    deps = orchestration.PipelineRuntimeDependencies(
        browser_session_factory=_Session,
        collector_cls=SimpleNamespace,
        detail_page_worker_cls=_Extractor,
        set_state_error=lambda state, error: None,
        process_task=process_task,
    )
    pool = orchestration.ConsumerPool(context, deps)
    pool._claim_slots = SimpleNamespace(release=lambda: None)

    await pool._worker(task_queue, orchestration.asyncio.Lock())

    assert tracker.runtime_state_calls == [{"stage": "consuming"}]

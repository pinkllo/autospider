from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.crawler.collector.llm_decision import LLMDecisionMaker
from autospider.field.field_decider import FieldDecider
from autospider.pipeline.orchestration import (
    ConsumerPool,
    PipelineRuntimeContext,
    PipelineRuntimeDependencies,
    PipelineSessionBundle,
    ProducerService,
)


@pytest.mark.asyncio
async def test_llm_decision_maker_injects_decision_context_into_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import autospider.crawler.collector.llm_decision as decision_module

    captured: dict[str, object] = {}

    def fake_render_template(_path, *, section, variables=None):
        if section == "ask_llm_decision_user_message":
            captured["variables"] = dict(variables or {})
        return section

    async def fake_ainvoke_with_stream(_llm, _messages):
        return object()

    monkeypatch.setattr(decision_module, "render_template", fake_render_template)
    monkeypatch.setattr(decision_module, "ainvoke_with_stream", fake_ainvoke_with_stream)
    monkeypatch.setattr(decision_module, "extract_response_text_from_llm_payload", lambda _response: "{}")
    monkeypatch.setattr(decision_module, "summarize_llm_payload", lambda _response: {})
    monkeypatch.setattr(
        decision_module,
        "parse_protocol_message",
        lambda _response: {"action": "scroll", "args": {"scroll_delta": [0, 500]}},
    )
    monkeypatch.setattr(decision_module, "append_llm_trace", lambda **_kwargs: None)

    decision_maker = LLMDecisionMaker(
        page=SimpleNamespace(url="https://example.com/list"),
        decider=SimpleNamespace(llm=object()),
        task_description="采集列表详情页",
        collected_urls=[],
        visited_detail_urls=set(),
        list_url="https://example.com/list",
        decision_context={
            "page_model": {"page_type": "list_page"},
            "current_plan": {"goal": "收集详情页链接"},
        },
    )

    await decision_maker.ask_for_decision(
        snapshot=SimpleNamespace(marks=[]),
        screenshot_base64="ZmFrZQ==",
    )

    variables = dict(captured["variables"])
    assert "list_page" in str(variables["decision_context"])
    assert "收集详情页链接" in str(variables["decision_context"])


@pytest.mark.asyncio
async def test_field_decider_injects_decision_context_into_navigation_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import autospider.field.field_decider as field_decider_module
    from autospider.domain.fields import FieldDefinition

    captured: dict[str, object] = {}

    def fake_render_template(_path, *, section, variables=None):
        if section == "navigate_to_field_user_message":
            captured["variables"] = dict(variables or {})
        return section

    async def fake_ainvoke_with_stream(_llm, _messages):
        return object()

    monkeypatch.setattr(field_decider_module, "render_template", fake_render_template)
    monkeypatch.setattr(field_decider_module, "ainvoke_with_stream", fake_ainvoke_with_stream)
    monkeypatch.setattr(field_decider_module, "extract_response_text_from_llm_payload", lambda _response: "{}")
    monkeypatch.setattr(field_decider_module, "summarize_llm_payload", lambda _response: {})
    monkeypatch.setattr(
        field_decider_module,
        "parse_protocol_message",
        lambda _response: {"action": "scroll", "args": {"scroll_delta": [0, 500]}},
    )
    monkeypatch.setattr(field_decider_module, "append_llm_trace", lambda **_kwargs: None)

    decider = FieldDecider(
        page=SimpleNamespace(url="https://example.com/detail"),
        decider=SimpleNamespace(llm=object()),
        decision_context={
            "page_model": {
                "page_type": "detail_page",
                "metadata": {"observations": "字段位于页面右侧信息块"},
            }
        },
    )

    await decider.decide_navigation(
        snapshot=SimpleNamespace(marks=[], scroll_info=None),
        screenshot_base64="ZmFrZQ==",
        field=FieldDefinition(name="title", description="公告标题"),
        nav_steps_count=0,
        nav_steps_summary="无",
        scroll_info=None,
        page_text_hit=True,
    )

    variables = dict(captured["variables"])
    assert "detail_page" in str(variables["decision_context"])
    assert "字段位于页面右侧信息块" in str(variables["decision_context"])


@pytest.mark.asyncio
async def test_producer_service_passes_decision_context_to_collector() -> None:
    captured: dict[str, object] = {}

    class FakeCollector:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.nav_steps = []
            self.common_detail_xpath = None

        async def run(self):
            return SimpleNamespace(collected_urls=["https://example.com/detail/1"])

    class FakeTracker:
        async def set_total(self, _total: int) -> None:
            return None

    class FakeChannel:
        async def seal(self) -> None:
            return None

        async def close_with_error(self, _error: str) -> None:
            return None

    class FakeListSession:
        page = SimpleNamespace(url="https://example.com/list")

        async def stop(self) -> None:
            return None

    context = PipelineRuntimeContext(
        list_url="https://example.com/list",
        anchor_url="https://example.com",
        page_state_signature="sig-entry",
        variant_label=None,
        task_description="采集详情页链接",
        execution_brief={},
        fields=[],
        output_dir="output",
        headless=True,
        explore_count=2,
        validate_count=1,
        consumer_workers=1,
        max_pages=3,
        target_url_count=8,
        guard_intervention_mode="interrupt",
        guard_thread_id="thread-1",
        selected_skills=[],
        channel=FakeChannel(),
        run_records={},
        summary={},
        tracker=FakeTracker(),
        skill_runtime=object(),
        sessions=PipelineSessionBundle(list_session=FakeListSession()),
        decision_context={"page_model": {"page_type": "list_page"}},
        world_snapshot={"world_model": {"page_models": {}}},
        failure_records=({"category": "navigation"},),
    )
    deps = PipelineRuntimeDependencies(
        browser_session_factory=lambda **_kwargs: None,
        collector_cls=FakeCollector,
        detail_page_worker_cls=object,
        set_state_error=lambda _state, _error: None,
        process_task=lambda **_kwargs: None,
    )

    await ProducerService(context, deps).run()

    assert captured["decision_context"] == {"page_model": {"page_type": "list_page"}}


@pytest.mark.asyncio
async def test_consumer_pool_passes_decision_payloads_to_detail_worker() -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self) -> None:
            self.page = SimpleNamespace(url="https://example.com/detail")

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class FakeWorker:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    async def fake_process_task(**_kwargs):
        return None

    class FakeChannel:
        async def fetch(self, *, max_items: int, timeout_s: int):
            return []

        async def is_drained(self) -> bool:
            return True

    context = PipelineRuntimeContext(
        list_url="https://example.com/list",
        anchor_url="https://example.com",
        page_state_signature="sig-entry",
        variant_label=None,
        task_description="采集详情页字段",
        execution_brief={},
        fields=[],
        output_dir="output",
        headless=True,
        explore_count=2,
        validate_count=1,
        consumer_workers=1,
        max_pages=3,
        target_url_count=8,
        guard_intervention_mode="interrupt",
        guard_thread_id="thread-1",
        selected_skills=[],
        channel=FakeChannel(),
        run_records={},
        summary={},
        tracker=SimpleNamespace(),
        skill_runtime=object(),
        sessions=PipelineSessionBundle(list_session=SimpleNamespace()),
        decision_context={"page_model": {"page_type": "detail_page"}},
        world_snapshot={"world_model": {"page_models": {"entry": {}}}},
        failure_records=({"category": "navigation", "detail": "timed_out"},),
    )
    deps = PipelineRuntimeDependencies(
        browser_session_factory=lambda **_kwargs: FakeSession(),
        collector_cls=object,
        detail_page_worker_cls=FakeWorker,
        set_state_error=lambda _state, _error: None,
        process_task=fake_process_task,
    )
    pool = ConsumerPool(context, deps)
    task_queue = asyncio.Queue()
    await task_queue.put(None)

    await pool._worker(task_queue, asyncio.Lock())

    assert captured["decision_context"] == {"page_model": {"page_type": "detail_page"}}
    assert captured["world_snapshot"] == {"world_model": {"page_models": {"entry": {}}}}
    assert captured["failure_records"] == [{"category": "navigation", "detail": "timed_out"}]

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.composition.graph.types import GraphResult
from autospider.composition.use_cases.benchmark_runtime import (
    BenchmarkRuntimeExecutor,
    BenchmarkRuntimeInterrupted,
)
from autospider.platform.llm.trace_stats import LLMTraceStats


class _FakePipeline:
    def __init__(self, result_factory):
        self._result_factory = result_factory

    async def run(self, *, cli_args, thread_id: str, request_id: str) -> GraphResult:
        return self._result_factory(cli_args=cli_args, thread_id=thread_id, request_id=request_id)


class _FakeResumer:
    def __init__(self, result_factories):
        self._result_factories = list(result_factories)
        self.calls: list[dict[str, object]] = []

    async def resume(self, *, thread_id: str, resume=None, use_command: bool = True) -> GraphResult:
        self.calls.append(
            {
                "thread_id": thread_id,
                "resume": resume,
                "use_command": use_command,
            }
        )
        if not self._result_factories:
            raise AssertionError("unexpected resume call")
        factory = self._result_factories.pop(0)
        return factory(thread_id=thread_id, resume=resume)


def test_benchmark_runtime_executor_auto_resumes_interrupts_and_aggregates_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from autospider.composition.use_cases import benchmark_runtime as runtime_module

    cleanup_calls: list[str] = []

    async def _fake_cleanup_browser_engine() -> None:
        cleanup_calls.append("cleanup")

    pipeline = _FakePipeline(
        lambda **kwargs: GraphResult(
            status="interrupted",
            entry_mode="chat_pipeline",
            thread_id=str(kwargs["thread_id"]),
            summary={
                "total_graph_steps": 4,
                "graph_steps_by_node": {
                    "route_entry": 1,
                    "chat_clarify": 1,
                    "chat_history_match": 1,
                    "__interrupt__": 1,
                },
            },
            interrupts=[
                {
                    "id": "interrupt-1",
                    "value": {"type": "chat_clarification", "question": "请补充字段"},
                }
            ],
        )
    )
    resumer = _FakeResumer(
        [
            lambda **kwargs: GraphResult(
                status="interrupted",
                entry_mode="chat_pipeline",
                thread_id=str(kwargs["thread_id"]),
                summary={
                    "total_graph_steps": 2,
                    "graph_steps_by_node": {"chat_collect_user_input": 1, "chat_clarify": 1},
                },
                interrupts=[
                    {
                        "id": "interrupt-2",
                        "value": {
                            "type": "history_task_select",
                            "options": [
                                {"index": 1, "type": "history"},
                                {"index": 2, "type": "new"},
                            ],
                        },
                    }
                ],
            ),
            lambda **kwargs: GraphResult(
                status="interrupted",
                entry_mode="chat_pipeline",
                thread_id=str(kwargs["thread_id"]),
                summary={
                    "total_graph_steps": 1,
                    "graph_steps_by_node": {"chat_review_task": 1},
                },
                interrupts=[
                    {
                        "id": "interrupt-3",
                        "value": {
                            "type": "chat_review",
                            "clarified_task": {
                                "list_url": "http://localhost/categories",
                                "task_description": "采集所有分类产品",
                                "fields": [
                                    {"name": "category", "description": "分类"},
                                    {"name": "product_name", "description": "产品名"},
                                ],
                                "group_by": "none",
                            },
                        },
                    }
                ],
            ),
            lambda **kwargs: GraphResult(
                status="partial_success",
                entry_mode="chat_pipeline",
                thread_id=str(kwargs["thread_id"]),
                summary={
                    "total_graph_steps": 3,
                    "graph_steps_by_node": {
                        "chat_prepare_execution_handoff": 1,
                        "aggregate_node": 1,
                        "finalize": 1,
                    },
                },
            ),
        ]
    )
    monkeypatch.setattr(BenchmarkRuntimeExecutor, "_ensure_runtime_ready", lambda self: None)
    monkeypatch.setattr(runtime_module, "_cleanup_browser_engine", _fake_cleanup_browser_engine)
    monkeypatch.setattr(
        runtime_module,
        "collect_trace_stats",
        lambda **kwargs: LLMTraceStats(
            llm_calls=3,
            calls_with_token_usage=3,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            token_usage_available=True,
        ),
    )

    summary = BenchmarkRuntimeExecutor(
        pipeline=pipeline,
        resumer=resumer,
        max_auto_resumes=5,
    ).execute("采集商品", {"output_dir": ".tmp/benchmark/runtime"})

    assert [call["resume"] for call in resumer.calls] == [
        {"answer": runtime_module._DEFAULT_CLARIFICATION_ANSWER},
        {"choice": 2},
        {
            "action": "override_task",
            "task": {
                "list_url": "http://localhost/categories",
                "task_description": "采集所有分类产品",
                "fields": [
                    {"name": "category", "description": "分类"},
                    {"name": "product_name", "description": "产品名"},
                ],
                "group_by": "category",
                "per_group_target_count": None,
                "total_target_count": None,
                "category_discovery_mode": "auto",
                "requested_categories": [],
                "category_examples": [],
            },
        },
    ]
    assert summary["graph_status"] == "partial_success"
    assert summary["total_graph_steps"] == 10
    assert summary["graph_steps_by_node"] == {
        "route_entry": 1,
        "chat_clarify": 2,
        "chat_history_match": 1,
        "__interrupt__": 1,
        "chat_collect_user_input": 1,
        "chat_review_task": 1,
        "chat_prepare_execution_handoff": 1,
        "aggregate_node": 1,
        "finalize": 1,
    }
    assert summary["llm_calls"] == 3
    assert summary["prompt_tokens"] == 10
    assert summary["completion_tokens"] == 5
    assert summary["total_tokens"] == 15
    assert cleanup_calls == ["cleanup", "cleanup"]


def test_benchmark_runtime_executor_raises_for_browser_intervention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _FakePipeline(
        lambda **kwargs: GraphResult(
            status="interrupted",
            entry_mode="chat_pipeline",
            thread_id=str(kwargs["thread_id"]),
            interrupts=[
                {
                    "id": "interrupt-1",
                    "value": {
                        "type": "browser_intervention",
                        "message": "需要人工点击验证码",
                    },
                }
            ],
        )
    )

    monkeypatch.setattr(BenchmarkRuntimeExecutor, "_ensure_runtime_ready", lambda self: None)

    with pytest.raises(BenchmarkRuntimeInterrupted, match="manual browser intervention"):
        BenchmarkRuntimeExecutor(pipeline=pipeline, resumer=_FakeResumer([])).execute("采集", {})


def test_benchmark_runtime_executor_raises_for_unknown_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _FakePipeline(
        lambda **kwargs: GraphResult(
            status="interrupted",
            entry_mode="chat_pipeline",
            thread_id=str(kwargs["thread_id"]),
            interrupts=[{"id": "interrupt-1", "value": {"type": "unexpected"}}],
        )
    )

    monkeypatch.setattr(BenchmarkRuntimeExecutor, "_ensure_runtime_ready", lambda self: None)

    with pytest.raises(BenchmarkRuntimeInterrupted, match="unsupported benchmark interrupt type"):
        BenchmarkRuntimeExecutor(pipeline=pipeline, resumer=_FakeResumer([])).execute("采集", {})

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from typing_extensions import TypedDict
from langgraph.graph import END, StateGraph

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.composition.graph.runner import GraphRunner
from autospider.composition.graph.stream_stats import GraphStreamStats
from autospider.composition.graph.types import GraphInput, GraphResult


@pytest.mark.asyncio
async def test_graph_runner_invoke_does_not_seed_empty_world_request_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_invoke_with_graph(
        self,
        graph_input,
        *,
        thread_id: str,
        expected_entry_mode: str | None = None,
    ) -> GraphResult:
        del self
        del thread_id
        del expected_entry_mode
        captured["graph_input"] = graph_input
        return GraphResult(status="success", entry_mode="chat_pipeline")

    monkeypatch.setattr(GraphRunner, "_invoke_with_graph", _fake_invoke_with_graph)

    runner = GraphRunner()
    await runner.invoke(GraphInput(entry_mode="chat_pipeline", cli_args={"request": "采集公告"}))

    initial_state = dict(captured["graph_input"] or {})
    meta = dict(initial_state.get("meta") or {})
    world = dict(initial_state.get("world") or {})

    assert meta["entry_mode"] == "chat_pipeline"
    assert "entry_mode" not in initial_state
    assert "thread_id" not in initial_state
    assert "request_id" not in initial_state
    assert "request_params" not in world


class _StatsState(TypedDict, total=False):
    meta: dict[str, str]
    status: str
    result: dict[str, object]


@pytest.mark.asyncio
async def test_graph_runner_invoke_collects_stream_step_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = StateGraph(_StatsState)
    graph.add_node(
        "finish",
        lambda state: {
            "status": "success",
            "result": {
                "status": "success",
                "summary": {"existing_metric": 3},
                "data": {"ok": True},
                "artifacts": [],
            },
        },
    )
    graph.set_entry_point("finish")
    graph.add_edge("finish", END)
    compiled = graph.compile()

    async def _fake_get_compiled_graph(self):
        del self
        return compiled

    monkeypatch.setattr(GraphRunner, "_get_compiled_graph", _fake_get_compiled_graph)

    runner = GraphRunner()
    result = await runner.invoke(GraphInput(entry_mode="chat_pipeline", cli_args={"request": "采集"}))

    assert result.summary["existing_metric"] == 3
    assert result.summary["total_graph_steps"] == 1
    assert result.summary["graph_steps_by_node"] == {"finish": 1}


@pytest.mark.asyncio
async def test_graph_runner_resume_collects_stream_step_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import autospider.composition.graph.runner as runner_module

    class _Snapshot:
        def __init__(self, *, interrupts: tuple[object, ...] = ()) -> None:
            self.values = {
                "meta": {"entry_mode": "chat_pipeline", "thread_id": "thread-1"},
                "status": "interrupted",
            }
            self.config = {"configurable": {"thread_id": "thread-1"}}
            self.interrupts = interrupts
            self.next = ()

    class _Graph:
        def __init__(self) -> None:
            self.calls = 0

        async def aget_state(self, _config):
            self.calls += 1
            return _Snapshot(interrupts=(object(),)) if self.calls == 1 else _Snapshot()

    graph = _Graph()

    @asynccontextmanager
    async def _fake_checkpointer_session():
        yield object()

    async def _fake_collect_stream_execution(_graph, graph_input, *, config):
        assert _graph is graph
        assert config["configurable"]["thread_id"] == "thread-1"
        assert graph_input is not None
        return (
            {
                "status": "success",
                "result": {
                    "status": "success",
                    "summary": {"existing_metric": 5},
                    "data": {"ok": True},
                    "artifacts": [],
                },
            },
            GraphStreamStats(
                total_graph_steps=2,
                graph_steps_by_node={"chat_review_task": 1, "chat_prepare_execution_handoff": 1},
            ),
        )

    monkeypatch.setattr(runner_module, "graph_checkpoint_enabled", lambda: True)
    monkeypatch.setattr(runner_module, "graph_checkpointer_session", _fake_checkpointer_session)
    monkeypatch.setattr(runner_module, "build_main_graph", lambda checkpointer=None: graph)
    monkeypatch.setattr(runner_module, "collect_stream_execution", _fake_collect_stream_execution)

    result = await GraphRunner().resume(
        thread_id="thread-1",
        resume={"action": "approve"},
        use_command=True,
    )

    assert result.status == "success"
    assert result.summary["existing_metric"] == 5
    assert result.summary["total_graph_steps"] == 2
    assert result.summary["graph_steps_by_node"] == {
        "chat_review_task": 1,
        "chat_prepare_execution_handoff": 1,
    }


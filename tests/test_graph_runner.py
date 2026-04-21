from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.composition.graph.runner import GraphRunner
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
    world = dict(initial_state.get("world") or {})

    assert "request_params" not in world


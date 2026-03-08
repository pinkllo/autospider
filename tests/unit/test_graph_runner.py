import asyncio
from types import SimpleNamespace

from autospider.graph.runner import GraphRunner
from autospider.graph.types import GraphInput


class _FakeGraph:
    def __init__(self, payload=None):
        self.payload = payload or {}
        self.last_config = None
        self.last_state = None

    async def ainvoke(self, state, config=None, **kwargs):
        self.last_state = state
        self.last_config = config
        return {
            **state,
            "status": "success",
            "summary": {"ok": True},
            "artifacts": [{"label": "x", "path": "output/x.json"}],
            "node_payload": {"result": {"value": 1}},
            "error_code": "",
            "error_message": "",
            **self.payload,
        }


def test_graph_runner_invoke_success(monkeypatch):
    fake_graph = _FakeGraph()
    monkeypatch.setattr(GraphRunner, "_compiled_graph", fake_graph)
    runner = GraphRunner()
    result = asyncio.run(
        runner.invoke(
            GraphInput(
                entry_mode="pipeline_run",
                cli_args={"list_url": "https://example.com"},
                request_id="req_test",
                invoked_at="2026-01-01T00:00:00",
                thread_id="thread_test",
            )
        )
    )

    assert result.status == "success"
    assert result.entry_mode == "pipeline_run"
    assert result.summary["ok"] is True
    assert result.artifacts[0]["path"] == "output/x.json"
    assert result.data["result"]["value"] == 1
    assert result.thread_id == "thread_test"
    assert fake_graph.last_config == {"configurable": {"thread_id": "thread_test"}}
    assert fake_graph.last_state["thread_id"] == "thread_test"


def test_graph_runner_invoke_interrupted(monkeypatch):
    interrupt = SimpleNamespace(id="interrupt_1", value={"message": "need human"})
    fake_graph = _FakeGraph(payload={"__interrupt__": [interrupt]})
    monkeypatch.setattr(GraphRunner, "_compiled_graph", fake_graph)

    runner = GraphRunner()
    result = asyncio.run(
        runner.invoke(
            GraphInput(
                entry_mode="pipeline_run",
                cli_args={},
                request_id="req_interrupt",
                invoked_at="2026-01-01T00:00:00",
                thread_id="thread_interrupt",
            )
        )
    )

    assert result.status == "interrupted"
    assert result.interrupts == [{"id": "interrupt_1", "value": {"message": "need human"}}]


def test_graph_runner_resume_requires_checkpoint():
    runner = GraphRunner()

    try:
        asyncio.run(runner.resume(thread_id="thread_resume"))
    except RuntimeError as exc:
        assert "GRAPH_CHECKPOINT_ENABLED" in str(exc)
    else:
        raise AssertionError("resume should require checkpoint support")


def test_graph_runner_inspect_requires_checkpoint():
    runner = GraphRunner()

    try:
        asyncio.run(runner.inspect(thread_id="thread_inspect"))
    except RuntimeError as exc:
        assert "GRAPH_CHECKPOINT_ENABLED" in str(exc)
    else:
        raise AssertionError("inspect should require checkpoint support")

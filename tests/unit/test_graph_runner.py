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


class _Snapshot:
    def __init__(self, *, values=None, config=None, interrupts=(), next_nodes=()):
        self.values = values or {}
        self.config = config or {}
        self.interrupts = interrupts
        self.next = next_nodes


class _CheckpointGraph(_FakeGraph):
    def __init__(self, snapshot):
        super().__init__()
        self.snapshot = snapshot

    async def aget_state(self, config=None):
        self.last_config = config
        return self.snapshot


def test_graph_runner_invoke_success(monkeypatch):
    fake_graph = _FakeGraph()
    monkeypatch.setattr(GraphRunner, "_compiled_graph", fake_graph)
    monkeypatch.setattr("autospider.graph.runner.graph_checkpoint_enabled", lambda: False)
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
    monkeypatch.setattr("autospider.graph.runner.graph_checkpoint_enabled", lambda: False)

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




def test_graph_runner_inspect_requires_checkpoint():
    runner = GraphRunner()

    try:
        asyncio.run(runner.inspect(thread_id="thread_inspect"))
    except RuntimeError as exc:
        assert "GRAPH_CHECKPOINT_ENABLED" in str(exc)
    else:
        raise AssertionError("inspect should require checkpoint support")


def test_graph_runner_inspect_validates_snapshot_identity(monkeypatch):
    runner = GraphRunner()
    snapshot = _Snapshot(
        values={"thread_id": "other-thread", "entry_mode": "pipeline_run"},
        config={"configurable": {"thread_id": "other-thread"}},
    )
    graph = _CheckpointGraph(snapshot)

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("autospider.graph.runner.graph_checkpoint_enabled", lambda: True)
    monkeypatch.setattr("autospider.graph.runner.graph_checkpointer_session", lambda: _Session())
    monkeypatch.setattr("autospider.graph.runner.build_main_graph", lambda checkpointer=None: graph)

    try:
        asyncio.run(runner.inspect(thread_id="thread_inspect"))
    except RuntimeError as exc:
        assert "checkpoint_thread_mismatch" in str(exc)
    else:
        raise AssertionError("inspect should validate checkpoint thread identity")


def test_graph_runner_resume_requires_entry_mode_in_snapshot(monkeypatch):
    runner = GraphRunner()
    snapshot = _Snapshot(
        values={"thread_id": "thread_resume"},
        config={"configurable": {"thread_id": "thread_resume"}},
    )
    graph = _CheckpointGraph(snapshot)

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("autospider.graph.runner.graph_checkpoint_enabled", lambda: True)
    monkeypatch.setattr("autospider.graph.runner.graph_checkpointer_session", lambda: _Session())
    monkeypatch.setattr("autospider.graph.runner.build_main_graph", lambda checkpointer=None: graph)

    try:
        asyncio.run(runner.resume(thread_id="thread_resume"))
    except RuntimeError as exc:
        assert "entry_mode" in str(exc)
    else:
        raise AssertionError("resume should require entry_mode in snapshot")

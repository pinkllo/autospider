import asyncio

from autospider.graph.runner import GraphRunner
from autospider.graph.types import GraphInput


class _FakeGraph:
    async def ainvoke(self, state):
        return {
            **state,
            "status": "success",
            "summary": {"ok": True},
            "artifacts": [{"label": "x", "path": "output/x.json"}],
            "node_payload": {"result": {"value": 1}},
            "error_code": "",
            "error_message": "",
        }


def test_graph_runner_invoke_success(monkeypatch):
    monkeypatch.setattr(GraphRunner, "_compiled_graph", _FakeGraph())
    runner = GraphRunner()
    result = asyncio.run(
        runner.invoke(
            GraphInput(
                entry_mode="pipeline_run",
                cli_args={"list_url": "https://example.com"},
                request_id="req_test",
                invoked_at="2026-01-01T00:00:00",
            )
        )
    )

    assert result.status == "success"
    assert result.entry_mode == "pipeline_run"
    assert result.summary["ok"] is True
    assert result.artifacts[0]["path"] == "output/x.json"
    assert result.data["result"]["value"] == 1

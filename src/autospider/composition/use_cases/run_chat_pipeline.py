from __future__ import annotations

from typing import Any, Protocol

from autospider.legacy.graph.types import GraphInput, GraphResult


class GraphRunnerProtocol(Protocol):
    async def invoke(self, graph_input: GraphInput) -> GraphResult: ...


class RunChatPipeline:
    def __init__(self, runner_factory: callable | None = None) -> None:
        self._runner_factory = runner_factory or _build_graph_runner

    async def run(
        self,
        *,
        cli_args: dict[str, Any],
        thread_id: str = "",
    ) -> GraphResult:
        graph_input = GraphInput(
            entry_mode="chat_pipeline",
            cli_args=dict(cli_args),
            thread_id=thread_id or GraphInput.model_fields["thread_id"].default_factory(),
        )
        return await self._runner_factory().invoke(graph_input)


def _build_graph_runner() -> GraphRunnerProtocol:
    from autospider.legacy.graph.runner import GraphRunner

    return GraphRunner()

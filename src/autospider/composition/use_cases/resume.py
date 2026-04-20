from __future__ import annotations

from typing import Any, Protocol

from autospider.composition.graph.types import GraphResult


class ResumableGraphRunner(Protocol):
    async def inspect(self, *, thread_id: str) -> GraphResult: ...

    async def resume(
        self,
        *,
        thread_id: str,
        resume: Any = None,
        use_command: bool = True,
    ) -> GraphResult: ...


class ResumeRun:
    def __init__(self, runner_factory: callable | None = None) -> None:
        self._runner_factory = runner_factory or _build_graph_runner

    async def inspect(self, *, thread_id: str) -> GraphResult:
        return await self._runner_factory().inspect(thread_id=thread_id)

    async def resume(
        self,
        *,
        thread_id: str,
        resume: Any = None,
        use_command: bool = True,
    ) -> GraphResult:
        return await self._runner_factory().resume(
            thread_id=thread_id,
            resume=resume,
            use_command=use_command,
        )


def _build_graph_runner() -> ResumableGraphRunner:
    from autospider.composition.graph.runner import GraphRunner

    return GraphRunner()

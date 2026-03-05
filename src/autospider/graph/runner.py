"""Graph 运行器。"""

from __future__ import annotations

from typing import Any

from .main_graph import build_main_graph
from .types import GraphError, GraphInput, GraphResult


class GraphRunner:
    """统一图执行入口。"""

    _compiled_graph = None

    def __init__(self) -> None:
        if GraphRunner._compiled_graph is None:
            GraphRunner._compiled_graph = build_main_graph()

    async def invoke(self, graph_input: GraphInput) -> GraphResult:
        """异步执行主图。"""
        initial_state = {
            "entry_mode": graph_input.entry_mode,
            "request_id": graph_input.request_id,
            "invoked_at": graph_input.invoked_at,
            "cli_args": dict(graph_input.cli_args),
            "normalized_params": {},
            "clarified_task": None,
            "subtask_results": [],
            "artifacts": [],
            "summary": {},
            "status": "",
            "error_code": "",
            "error_message": "",
        }

        final_state: dict[str, Any] = await GraphRunner._compiled_graph.ainvoke(initial_state)
        error_code = str(final_state.get("error_code") or "")
        error_message = str(final_state.get("error_message") or "")
        error = GraphError(code=error_code, message=error_message) if error_code else None

        status = str(final_state.get("status") or "success")
        if status not in {"success", "partial_success", "failed"}:
            status = "failed" if error else "success"

        return GraphResult(
            status=status,  # type: ignore[arg-type]
            entry_mode=graph_input.entry_mode,
            summary=dict(final_state.get("summary") or {}),
            artifacts=list(final_state.get("artifacts") or []),
            error=error,
            data=dict(final_state.get("node_payload") or {}),
        )

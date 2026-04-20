"""Graph 运行器。"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from langgraph.types import Command

from autospider.platform.config.runtime import config
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context
from .checkpoint import graph_checkpoint_enabled, graph_checkpointer_session
from .main_graph import build_main_graph
from .workflow_access import coerce_workflow_state
from .state_access import select_artifacts, select_error, select_result_state, select_summary
from .types import GraphError, GraphInput, GraphResult


class GraphRunner:
    """统一图执行入口。"""

    _compiled_graph = None
    _compile_lock: asyncio.Lock | None = None

    def __init__(self) -> None:
        if GraphRunner._compile_lock is None:
            GraphRunner._compile_lock = asyncio.Lock()

    async def _get_compiled_graph(self):
        if graph_checkpoint_enabled():
            return None

        if GraphRunner._compiled_graph is not None:
            return GraphRunner._compiled_graph

        assert GraphRunner._compile_lock is not None
        async with GraphRunner._compile_lock:
            if GraphRunner._compiled_graph is None:
                GraphRunner._compiled_graph = build_main_graph()
        return GraphRunner._compiled_graph

    def _invoke_supports_trace_id(self) -> bool:
        return "trace_id" in inspect.signature(self._invoke_with_graph).parameters

    @staticmethod
    def _invoke_config(thread_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
        configurable = {"thread_id": thread_id}
        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id
        return {
            "configurable": configurable,
            "recursion_limit": max(1, int(config.graph_checkpoint.recursion_limit)),
        }

    @staticmethod
    def _validate_snapshot_identity(
        snapshot: Any, *, thread_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        snapshot_values = dict(getattr(snapshot, "values", {}) or {})
        snapshot_config = dict(getattr(snapshot, "config", {}) or {})
        configurable = dict(snapshot_config.get("configurable") or {})
        workflow = coerce_workflow_state(snapshot_values)
        snapshot_thread_id = str(
            dict(workflow.get("meta") or {}).get("thread_id")
            or snapshot_values.get("thread_id")
            or configurable.get("thread_id")
            or ""
        )
        if snapshot_thread_id != thread_id:
            raise RuntimeError(
                f"checkpoint_thread_mismatch: expected={thread_id}, actual={snapshot_thread_id or '<missing>'}"
            )
        entry_mode = str(
            dict(workflow.get("meta") or {}).get("entry_mode")
            or snapshot_values.get("entry_mode")
            or ""
        ).strip()
        if not entry_mode:
            raise RuntimeError("无法从 checkpoint 状态中恢复 entry_mode")
        return snapshot_values, configurable

    @staticmethod
    def _normalize_interrupts(raw_interrupts: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in list(raw_interrupts or []):
            interrupt_id = getattr(item, "id", "")
            value = getattr(item, "value", None)
            if not interrupt_id and isinstance(item, dict):
                interrupt_id = str(item.get("id") or "")
                value = item.get("value")
            normalized.append({"id": str(interrupt_id), "value": value})
        return normalized

    @staticmethod
    def _resolve_entry_mode(
        final_state: dict[str, Any],
        *,
        expected_entry_mode: str | None,
        snapshot_values: dict[str, Any] | None,
    ) -> str:
        entry_mode = str(expected_entry_mode or "").strip()
        if entry_mode:
            return entry_mode
        final_meta = dict(coerce_workflow_state(final_state).get("meta") or {})
        entry_mode = str(
            final_meta.get("entry_mode") or final_state.get("entry_mode") or ""
        ).strip()
        if entry_mode:
            return entry_mode
        if snapshot_values:
            snapshot_meta = dict(coerce_workflow_state(snapshot_values).get("meta") or {})
            entry_mode = str(
                snapshot_meta.get("entry_mode") or snapshot_values.get("entry_mode") or ""
            ).strip()
            if entry_mode:
                return entry_mode
        raise RuntimeError("无法从 checkpoint 状态中恢复 entry_mode")

    def _build_result(
        self,
        *,
        final_state: dict[str, Any],
        thread_id: str,
        expected_entry_mode: str | None = None,
        snapshot: Any | None = None,
    ) -> GraphResult:
        snapshot_values = dict(getattr(snapshot, "values", {}) or {})
        snapshot_config = dict(getattr(snapshot, "config", {}) or {})

        typed_error = select_error(final_state, snapshot_values=snapshot_values)
        error_code = str(
            typed_error.get("code")
            or final_state.get("error_code")
            or snapshot_values.get("error_code")
            or ""
        )
        error_message = str(
            typed_error.get("message")
            or final_state.get("error_message")
            or snapshot_values.get("error_message")
            or ""
        )
        error = GraphError(code=error_code, message=error_message) if error_code else None

        interrupts = self._normalize_interrupts(
            final_state.get("__interrupt__") or getattr(snapshot, "interrupts", ())
        )
        status = str(final_state.get("status") or snapshot_values.get("status") or "success")
        if interrupts:
            status = "interrupted"
        elif status not in {"success", "partial_success", "failed", "no_data"}:
            status = "failed" if error else "success"

        result_state = select_result_state(final_state) or select_result_state(snapshot_values)
        summary = select_summary(final_state, snapshot_values=snapshot_values)
        if thread_id:
            summary.setdefault("thread_id", thread_id)

        checkpoint_id = ""
        configurable = snapshot_config.get("configurable")
        if isinstance(configurable, dict):
            checkpoint_id = str(configurable.get("checkpoint_id") or "")

        entry_mode = self._resolve_entry_mode(
            final_state,
            expected_entry_mode=expected_entry_mode,
            snapshot_values=snapshot_values,
        )

        return GraphResult(
            status=status,  # type: ignore[arg-type]
            entry_mode=entry_mode,  # type: ignore[arg-type]
            summary=summary,
            artifacts=select_artifacts(final_state, snapshot_values=snapshot_values),
            error=error,
            data=dict(
                result_state.get("data")
                or final_state.get("result_context")
                or snapshot_values.get("result_context")
                or {}
            ),
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            next_nodes=[str(node) for node in list(getattr(snapshot, "next", ()) or [])],
            interrupts=interrupts,
        )

    async def _invoke_with_graph(
        self,
        graph_input: dict[str, Any] | Command | None,
        *,
        thread_id: str,
        expected_entry_mode: str | None = None,
        trace_id: str = "",
    ) -> GraphResult:
        resolved_trace_id = str(trace_id or thread_id).strip()
        set_run_context(run_id=thread_id, trace_id=resolved_trace_id)
        try:
            cached_graph = await self._get_compiled_graph()
            if cached_graph is not None:
                final_state = await cached_graph.ainvoke(
                    graph_input,
                    config=self._invoke_config(thread_id),
                )
                return self._build_result(
                    final_state=dict(final_state or {}),
                    thread_id=thread_id,
                    expected_entry_mode=expected_entry_mode,
                )

            async with graph_checkpointer_session() as checkpointer:
                if checkpointer is None:
                    raise RuntimeError("Graph checkpointer 未启用")
                graph = build_main_graph(checkpointer=checkpointer)
                invoke_config = self._invoke_config(thread_id)
                final_state = await graph.ainvoke(graph_input, config=invoke_config)
                snapshot = await graph.aget_state(invoke_config)
                return self._build_result(
                    final_state=dict(final_state or {}),
                    thread_id=thread_id,
                    expected_entry_mode=expected_entry_mode,
                    snapshot=snapshot,
                )
        finally:
            clear_run_context()

    async def invoke(self, graph_input: GraphInput) -> GraphResult:
        """异步执行主图。"""
        initial_state = {
            "meta": {
                "entry_mode": graph_input.entry_mode,
                "thread_id": graph_input.thread_id,
                "request_id": graph_input.request_id,
            },
            "entry_mode": graph_input.entry_mode,
            "thread_id": graph_input.thread_id,
            "request_id": graph_input.request_id,
            "invoked_at": graph_input.invoked_at,
            "cli_args": dict(graph_input.cli_args),
            "conversation": {
                "status": "",
                "flow_state": "",
                "review_state": "",
                "normalized_params": {},
                "clarified_task": None,
                "chat_history": [],
                "chat_turn_count": 0,
                "chat_max_turns": 0,
                "pending_question": "",
                "matched_skills": [],
                "selected_skills": [],
            },
            "world": {"collection_config": {}, "world_model": {}, "failure_records": []},
            "control": {
                "current_plan": {},
                "task_plan": None,
                "plan_knowledge": "",
                "stage_status": "",
                "active_strategy": {},
            },
            "execution": {"dispatch_summary": {}, "subtask_results": []},
            "result": {"status": "", "summary": {}, "data": {}, "artifacts": []},
            "error": None,
            "normalized_params": {},
            "status": "",
            "error_code": "",
            "error_message": "",
        }
        invoke_kwargs: dict[str, Any] = {
            "thread_id": graph_input.thread_id,
            "expected_entry_mode": graph_input.entry_mode,
        }
        if self._invoke_supports_trace_id():
            invoke_kwargs["trace_id"] = graph_input.request_id
        return await self._invoke_with_graph(initial_state, **invoke_kwargs)

    async def inspect(self, *, thread_id: str) -> GraphResult:
        """读取已持久化线程的当前状态。"""
        if not graph_checkpoint_enabled():
            raise RuntimeError("当前未启用 GRAPH_CHECKPOINT_ENABLED，无法 inspect 图线程")

        async with graph_checkpointer_session() as checkpointer:
            if checkpointer is None:
                raise RuntimeError("Graph checkpointer 未启用")
            graph = build_main_graph(checkpointer=checkpointer)
            snapshot = await graph.aget_state(self._invoke_config(thread_id))
            snapshot_values, _ = self._validate_snapshot_identity(snapshot, thread_id=thread_id)
            if not snapshot_values and not getattr(snapshot, "interrupts", ()):
                raise RuntimeError(f"未找到 thread_id={thread_id} 的图状态")
            return self._build_result(final_state={}, thread_id=thread_id, snapshot=snapshot)

    async def resume(
        self,
        *,
        thread_id: str,
        resume: Any = None,
        use_command: bool = True,
    ) -> GraphResult:
        """恢复已持久化的图线程。"""
        if not graph_checkpoint_enabled():
            raise RuntimeError("当前未启用 GRAPH_CHECKPOINT_ENABLED，无法 resume 图线程")

        graph_input: Command | None = Command(resume=resume) if use_command else None
        async with graph_checkpointer_session() as checkpointer:
            if checkpointer is None:
                raise RuntimeError("Graph checkpointer 未启用")
            graph = build_main_graph(checkpointer=checkpointer)
            invoke_config = self._invoke_config(thread_id)
            snapshot = await graph.aget_state(invoke_config)
            snapshot_values, _ = self._validate_snapshot_identity(snapshot, thread_id=thread_id)
            if not snapshot_values and not getattr(snapshot, "interrupts", ()):
                raise RuntimeError(f"未找到 thread_id={thread_id} 的图状态")
            snapshot_meta = dict(coerce_workflow_state(snapshot_values).get("meta") or {})
            resolved_trace_id = str(
                snapshot_meta.get("request_id") or snapshot_values.get("request_id") or thread_id
            )
            set_run_context(run_id=thread_id, trace_id=resolved_trace_id)
            try:
                final_state = await graph.ainvoke(graph_input, config=invoke_config)
                resumed_snapshot = await graph.aget_state(invoke_config)
                return self._build_result(
                    final_state=dict(final_state or {}),
                    thread_id=thread_id,
                    snapshot=resumed_snapshot,
                )
            finally:
                clear_run_context()

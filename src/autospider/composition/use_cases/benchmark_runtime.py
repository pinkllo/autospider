"""Runtime executor for real benchmark scenarios without importing the CLI package."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
from typing import Any
from uuid import uuid4

from autospider.composition.graph.types import GraphResult
from autospider.platform.llm.trace_stats import collect_trace_stats
from autospider.platform.persistence.redis.pool import get_sync_client
from autospider.platform.persistence.sql.orm.engine import init_db
from autospider.platform.shared_kernel.grouping_semantics import normalize_grouping_semantics
from .resume import ResumeRun
from .run_chat_pipeline import RunChatPipeline

_AUTO_RESUME_LIMIT = 12
_DEFAULT_CLARIFICATION_ANSWER = (
    "请严格按当前 benchmark 请求执行；如果页面存在分类、Tab 或频道切换，需要覆盖所有相关分类，不要只采集当前默认分类。"
)


class BenchmarkRuntimeUnavailable(RuntimeError):
    """Raised when the local runtime dependencies required by benchmark are unavailable."""


class BenchmarkRuntimeInterrupted(RuntimeError):
    """Raised when benchmark automation cannot safely continue a graph interrupt."""


@dataclass(slots=True)
class _StepTotals:
    total_graph_steps: int = 0
    graph_steps_by_node: dict[str, int] = field(default_factory=dict)

    def add(self, graph_result: GraphResult) -> None:
        summary = dict(graph_result.summary or {})
        self.total_graph_steps += _as_int(summary.get("total_graph_steps"))
        for node_name, count in dict(summary.get("graph_steps_by_node") or {}).items():
            normalized_name = str(node_name).strip()
            if not normalized_name:
                continue
            self.graph_steps_by_node[normalized_name] = (
                self.graph_steps_by_node.get(normalized_name, 0) + _as_int(count)
            )

    def apply(self, graph_result: GraphResult) -> GraphResult:
        summary = dict(graph_result.summary or {})
        summary["total_graph_steps"] = self.total_graph_steps
        summary["graph_steps_by_node"] = dict(self.graph_steps_by_node)
        graph_result.summary = summary
        return graph_result


class BenchmarkRuntimeExecutor:
    def __init__(
        self,
        pipeline: RunChatPipeline | None = None,
        resumer: ResumeRun | None = None,
        max_auto_resumes: int = _AUTO_RESUME_LIMIT,
    ) -> None:
        self._pipeline = pipeline or RunChatPipeline()
        self._resumer = resumer or ResumeRun()
        self._max_auto_resumes = max(1, int(max_auto_resumes))

    def execute(self, request: str, cli_overrides: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runtime_ready()
        thread_id = uuid4().hex
        graph_result = _run_async_safely(
            self._execute_graph(
                request=request,
                cli_overrides=dict(cli_overrides),
                thread_id=thread_id,
            )
        )
        return _build_execution_summary(graph_result, thread_id=thread_id)

    async def _execute_graph(
        self,
        *,
        request: str,
        cli_overrides: dict[str, Any],
        thread_id: str,
    ) -> GraphResult:
        await _cleanup_browser_engine()
        try:
            current = await self._pipeline.run(
                cli_args={"request": request, **dict(cli_overrides)},
                thread_id=thread_id,
                request_id=thread_id,
            )
            totals = _StepTotals()
            totals.add(current)
            attempts = 0
            while str(current.status or "") == "interrupted":
                attempts += 1
                if attempts > self._max_auto_resumes:
                    raise BenchmarkRuntimeInterrupted(
                        f"benchmark exceeded auto-resume limit: {self._max_auto_resumes}"
                    )
                resume_payload = _build_interrupt_resume_payload(current)
                current = await self._resumer.resume(
                    thread_id=str(current.thread_id or thread_id),
                    resume=resume_payload,
                    use_command=True,
                )
                totals.add(current)
            return totals.apply(current)
        finally:
            await _cleanup_browser_engine()

    def _ensure_runtime_ready(self) -> None:
        try:
            init_db()
        except Exception as exc:  # noqa: BLE001
            raise BenchmarkRuntimeUnavailable(f"database unavailable: {exc}") from exc
        try:
            client = get_sync_client()
            if client is None:
                raise RuntimeError("redis client unavailable")
            client.ping()
        except Exception as exc:  # noqa: BLE001
            raise BenchmarkRuntimeUnavailable(f"redis unavailable: {exc}") from exc
        try:
            import playwright.async_api  # noqa: F401
        except ImportError as exc:
            raise BenchmarkRuntimeUnavailable(f"playwright unavailable: {exc}") from exc


def execute_benchmark_graph(request: str, cli_overrides: dict[str, Any]) -> dict[str, Any]:
    return BenchmarkRuntimeExecutor().execute(request, cli_overrides)


async def _cleanup_browser_engine() -> None:
    try:
        from autospider.platform.browser.engine import shutdown_browser_engine

        await shutdown_browser_engine()
    except Exception:
        return None


def _build_interrupt_resume_payload(graph_result: GraphResult) -> dict[str, Any]:
    payload = _primary_interrupt_payload(graph_result)
    if payload is None:
        raise BenchmarkRuntimeInterrupted("graph interrupted without a resume payload")
    interrupt_type = str(payload.get("type") or "").strip().lower()
    if interrupt_type == "chat_clarification":
        return {"answer": _DEFAULT_CLARIFICATION_ANSWER}
    if interrupt_type == "chat_review":
        return _build_chat_review_resume_payload(payload)
    if interrupt_type == "history_task_select":
        return {"choice": _select_new_history_task_option(payload)}
    if interrupt_type == "browser_intervention":
        message = str(payload.get("message") or "browser intervention required").strip()
        raise BenchmarkRuntimeInterrupted(
            f"benchmark requires manual browser intervention: {message}"
        )
    raise BenchmarkRuntimeInterrupted(f"unsupported benchmark interrupt type: {interrupt_type}")


def _build_execution_summary(graph_result: GraphResult, *, thread_id: str) -> dict[str, Any]:
    summary = dict(graph_result.summary or {})
    summary["graph_status"] = str(graph_result.status or "")
    summary["thread_id"] = str(graph_result.thread_id or thread_id)
    trace_stats = collect_trace_stats(
        run_id=summary["thread_id"],
        trace_id=str(summary.get("request_id") or summary["thread_id"]),
    )
    summary.update(trace_stats.to_payload())
    return summary


def _primary_interrupt_payload(graph_result: GraphResult) -> dict[str, Any] | None:
    for item in list(graph_result.interrupts or []):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, dict):
            return value
    return None


def _select_new_history_task_option(payload: dict[str, Any]) -> int:
    options = list(payload.get("options") or [])
    for option in options:
        if str(option.get("type") or "").strip().lower() != "new":
            continue
        choice = _as_int(option.get("index"))
        if choice > 0:
            return choice
    raise BenchmarkRuntimeInterrupted("history_task_select missing new-task option")


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _build_chat_review_resume_payload(payload: dict[str, Any]) -> dict[str, Any]:
    task = dict(payload.get("clarified_task") or {})
    if not _should_force_category_grouping(task):
        return {"action": "approve"}
    updated_task = dict(task)
    updated_task.update(normalize_grouping_semantics({**task, "group_by": "category"}))
    return {"action": "override_task", "task": updated_task}


def _should_force_category_grouping(task: dict[str, Any]) -> bool:
    grouping = normalize_grouping_semantics(task)
    if grouping["group_by"] == "category":
        return False
    field_names = {
        str(item.get("name") or "").strip().lower()
        for item in list(task.get("fields") or [])
        if isinstance(item, dict)
    }
    return "category" in field_names or "category_path" in field_names


def _run_async_safely(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _run_in_thread(coro)


def _run_in_thread(coro: Any) -> Any:
    result_holder: dict[str, object] = {"result": None, "error": None}

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_holder["result"] = loop.run_until_complete(coro)
        except Exception as exc:  # noqa: BLE001
            result_holder["error"] = exc
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            asyncio.set_event_loop(None)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if result_holder["error"] is not None:
        raise result_holder["error"]  # type: ignore[misc]
    return result_holder["result"]

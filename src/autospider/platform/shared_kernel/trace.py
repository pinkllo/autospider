from __future__ import annotations

from contextvars import ContextVar

from .ids import RunId

_RUN_ID: ContextVar[RunId | None] = ContextVar("autospider_run_id", default=None)
_TRACE_ID: ContextVar[str | None] = ContextVar("autospider_trace_id", default=None)


def set_run_context(*, run_id: RunId | str | None, trace_id: str | None) -> None:
    normalized_run_id = None if run_id is None else RunId(str(run_id))
    normalized_trace_id = None if trace_id is None else str(trace_id)
    _RUN_ID.set(normalized_run_id)
    _TRACE_ID.set(normalized_trace_id)


def clear_run_context() -> None:
    _RUN_ID.set(None)
    _TRACE_ID.set(None)


def get_run_id() -> str | None:
    run_id = _RUN_ID.get()
    return None if run_id is None else str(run_id)


def get_trace_id() -> str | None:
    trace_id = _TRACE_ID.get()
    return None if trace_id is None else str(trace_id)

from __future__ import annotations

from typing import TypeVar

from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id

T = TypeVar("T")


def require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id


def failed_result(trace_id: str, *, code: str, message: str) -> ResultEnvelope[T]:
    error = ErrorInfo(kind="domain", code=code, message=message)
    return ResultEnvelope.failed(trace_id=trace_id, errors=[error])

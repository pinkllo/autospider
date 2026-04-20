from __future__ import annotations

from autospider.contexts.chat.application.dto import (
    ClarifiedTaskDTO,
    FinalizeTaskInput,
    to_task_dto,
)
from autospider.contexts.chat.domain.ports import SessionRepository
from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class FinalizeTask:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def run(self, command: FinalizeTaskInput) -> ResultEnvelope[ClarifiedTaskDTO]:
        trace_id = _require_trace_id()
        session = await self._repository.get(command.session_id)
        if session is None:
            return _failed(trace_id, "chat.session_not_found", "chat session not found")
        if session.clarified_task is None:
            return _failed(trace_id, "chat.task_not_ready", "clarified task is not ready")
        return ResultEnvelope.success(data=to_task_dto(session.clarified_task), trace_id=trace_id)


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id


def _failed(trace_id: str, code: str, message: str) -> ResultEnvelope[ClarifiedTaskDTO]:
    error = ErrorInfo(kind="domain", code=code, message=message)
    return ResultEnvelope.failed(trace_id=trace_id, errors=[error])

from __future__ import annotations

from autospider.contexts.chat.application.dto import (
    ClarifiedTaskDTO,
    FinalizeTaskInput,
    to_task_dto,
)
from autospider.contexts.chat.application.use_cases._result_support import (
    failed_result,
    require_trace_id,
)
from autospider.contexts.chat.domain.ports import SessionRepository
from autospider.platform.shared_kernel.result import ResultEnvelope


class FinalizeTask:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def run(self, command: FinalizeTaskInput) -> ResultEnvelope[ClarifiedTaskDTO]:
        trace_id = require_trace_id()
        session = await self._repository.get(command.session_id)
        if session is None:
            return failed_result(trace_id, "chat.session_not_found", "chat session not found")
        if session.clarified_task is None:
            return failed_result(trace_id, "chat.task_not_ready", "clarified task is not ready")
        return ResultEnvelope.success(data=to_task_dto(session.clarified_task), trace_id=trace_id)

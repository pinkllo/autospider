from __future__ import annotations

from uuid import uuid4

from autospider.contexts.chat.application.dto import (
    ClarificationSessionDTO,
    StartClarificationInput,
    to_session_dto,
)
from autospider.contexts.chat.domain.ports import LLMClarifier, SessionRepository
from autospider.contexts.chat.domain.services import ClarificationSessionService
from autospider.platform.shared_kernel.errors import DomainError
from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class StartClarification:
    def __init__(self, repository: SessionRepository, clarifier: LLMClarifier) -> None:
        self._repository = repository
        self._clarifier = clarifier
        self._service = ClarificationSessionService()

    async def run(
        self,
        command: StartClarificationInput,
    ) -> ResultEnvelope[ClarificationSessionDTO]:
        trace_id = _require_trace_id()
        try:
            session = self._service.start_session(str(uuid4()), command.initial_request)
            result = await self._clarifier.clarify(
                list(session.turns),
                available_skills=list(command.available_skills),
                selected_skills=list(command.selected_skills),
                selected_skills_context=command.selected_skills_context,
            )
            updated, _ = self._service.apply_result(session, result)
            await self._repository.save(updated)
        except DomainError as exc:
            return _failed(trace_id, exc)
        return ResultEnvelope.success(data=to_session_dto(updated, result), trace_id=trace_id)


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id


def _failed(
    trace_id: str,
    exc: DomainError,
) -> ResultEnvelope[ClarificationSessionDTO]:
    error = ErrorInfo(kind="domain", code=exc.code, message=str(exc))
    return ResultEnvelope.failed(trace_id=trace_id, errors=[error])

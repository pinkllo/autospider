from __future__ import annotations

from autospider.contexts.chat.application.dto import (
    AdvanceDialogueInput,
    ClarificationSessionDTO,
    to_session_dto,
)
from autospider.contexts.chat.domain.ports import LLMClarifier, SessionRepository
from autospider.contexts.chat.domain.services import ClarificationSessionService
from autospider.platform.shared_kernel.errors import DomainError
from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class AdvanceDialogue:
    def __init__(self, repository: SessionRepository, clarifier: LLMClarifier) -> None:
        self._repository = repository
        self._clarifier = clarifier
        self._service = ClarificationSessionService()

    async def run(
        self,
        command: AdvanceDialogueInput,
    ) -> ResultEnvelope[ClarificationSessionDTO]:
        trace_id = _require_trace_id()
        session = await self._repository.get(command.session_id)
        if session is None:
            return _failed(trace_id, "chat.session_not_found", "chat session not found")

        try:
            updated_session = self._service.append_user_message(session, command.user_message)
            result = await self._clarifier.clarify(
                list(updated_session.turns),
                available_skills=list(command.available_skills),
                selected_skills=list(command.selected_skills),
                selected_skills_context=command.selected_skills_context,
            )
            updated_session, _ = self._service.apply_result(updated_session, result)
            await self._repository.save(updated_session)
        except DomainError as exc:
            return _failed(trace_id, exc.code, str(exc))
        return ResultEnvelope.success(
            data=to_session_dto(updated_session, result), trace_id=trace_id
        )


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id


def _failed(
    trace_id: str,
    code: str,
    message: str,
) -> ResultEnvelope[ClarificationSessionDTO]:
    error = ErrorInfo(kind="domain", code=code, message=message)
    return ResultEnvelope.failed(trace_id=trace_id, errors=[error])

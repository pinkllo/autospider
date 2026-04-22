from __future__ import annotations

from autospider.contexts.chat.application.dto import (
    AdvanceDialogueInput,
    ClarificationSessionDTO,
    to_session_dto,
)
from autospider.contexts.chat.application.use_cases._result_support import (
    failed_result,
    require_trace_id,
)
from autospider.contexts.chat.domain.ports import LLMClarifier, SessionRepository
from autospider.contexts.chat.domain.services import ClarificationSessionService
from autospider.platform.shared_kernel.errors import DomainError
from autospider.platform.shared_kernel.result import ResultEnvelope


class AdvanceDialogue:
    def __init__(self, repository: SessionRepository, clarifier: LLMClarifier) -> None:
        self._repository = repository
        self._clarifier = clarifier
        self._service = ClarificationSessionService()

    async def run(
        self,
        command: AdvanceDialogueInput,
    ) -> ResultEnvelope[ClarificationSessionDTO]:
        trace_id = require_trace_id()
        session = await self._repository.get(command.session_id)
        if session is None:
            return failed_result(trace_id, "chat.session_not_found", "chat session not found")

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
            return failed_result(trace_id, exc.code, str(exc))
        return ResultEnvelope.success(
            data=to_session_dto(updated_session, result), trace_id=trace_id
        )

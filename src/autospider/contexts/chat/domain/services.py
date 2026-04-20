from __future__ import annotations

from dataclasses import replace

from autospider.platform.shared_kernel.errors import DomainError

from .events import TaskClarified
from .model import ClarificationResult, ClarificationSession, DialogueMessage


class ClarificationSessionService:
    def start_session(self, session_id: str, initial_request: str) -> ClarificationSession:
        message = DialogueMessage(role="user", content=initial_request.strip())
        if not message.content:
            raise DomainError("initial request must not be empty", code="chat.empty_request")
        return ClarificationSession(session_id=session_id, turns=(message,))

    def append_user_message(
        self,
        session: ClarificationSession,
        user_message: str,
    ) -> ClarificationSession:
        message = DialogueMessage(role="user", content=user_message.strip())
        if not message.content:
            raise DomainError("user message must not be empty", code="chat.empty_message")
        return replace(session, turns=(*session.turns, message))

    def apply_result(
        self,
        session: ClarificationSession,
        result: ClarificationResult,
    ) -> tuple[ClarificationSession, TaskClarified | None]:
        if result.status == "ready":
            if result.task is None:
                raise DomainError("ready result requires task", code="chat.ready_without_task")
            updated = replace(session, status="finalized", clarified_task=result.task)
            return updated, TaskClarified(session_id=session.session_id, task=result.task)

        if result.status == "reject":
            if not result.reason:
                raise DomainError(
                    "reject result requires reason", code="chat.reject_without_reason"
                )
            return replace(session, status="abandoned"), None

        if not result.next_question:
            raise DomainError(
                "clarification result requires next question",
                code="chat.missing_question",
            )
        assistant_turn = DialogueMessage(role="assistant", content=result.next_question)
        updated = replace(session, turns=(*session.turns, assistant_turn))
        return updated, None

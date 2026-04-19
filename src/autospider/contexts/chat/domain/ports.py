from __future__ import annotations

from typing import Protocol

from .model import ClarificationResult, ClarificationSession, DialogueMessage


class SessionRepository(Protocol):
    async def get(self, session_id: str) -> ClarificationSession | None: ...

    async def save(self, session: ClarificationSession) -> None: ...


class LLMClarifier(Protocol):
    async def clarify(
        self,
        history: list[DialogueMessage],
        *,
        available_skills: list[dict[str, str]] | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        selected_skills_context: str | None = None,
    ) -> ClarificationResult: ...

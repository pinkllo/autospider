from __future__ import annotations

from autospider.common.llm.task_clarifier import TaskClarifier
from autospider.contexts.chat.domain.model import ClarificationResult, DialogueMessage


class TaskClarifierAdapter:
    def __init__(self, clarifier: TaskClarifier | None = None) -> None:
        self._clarifier = clarifier or TaskClarifier()

    @property
    def llm(self):  # type: ignore[no-untyped-def]
        return self._clarifier.llm

    async def clarify(
        self,
        history: list[DialogueMessage],
        *,
        available_skills: list[dict[str, str]] | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        selected_skills_context: str | None = None,
    ) -> ClarificationResult:
        return await self._clarifier.clarify(
            history,
            available_skills=available_skills,
            selected_skills=selected_skills,
            selected_skills_context=selected_skills_context,
        )

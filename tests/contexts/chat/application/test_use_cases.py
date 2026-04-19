from __future__ import annotations

import pytest

from autospider.contexts.chat.application.dto import AdvanceDialogueInput, StartClarificationInput
from autospider.contexts.chat.application.use_cases import AdvanceDialogue, StartClarification
from autospider.contexts.chat.domain.model import (
    ClarificationResult,
    ClarificationSession,
    ClarifiedTask,
    DialogueMessage,
    RequestedField,
)
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, ClarificationSession] = {}

    async def get(self, session_id: str) -> ClarificationSession | None:
        return self._sessions.get(session_id)

    async def save(self, session: ClarificationSession) -> None:
        self._sessions[session.session_id] = session


class StubClarifier:
    def __init__(self, result: ClarificationResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    async def clarify(
        self,
        history: list[DialogueMessage],
        *,
        available_skills: list[dict[str, str]] | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        selected_skills_context: str | None = None,
    ) -> ClarificationResult:
        assert history
        self.calls.append(
            {
                "history": history,
                "available_skills": available_skills,
                "selected_skills": selected_skills,
                "selected_skills_context": selected_skills_context,
            }
        )
        return self._result


@pytest.mark.asyncio
async def test_start_clarification_returns_finalized_session() -> None:
    set_run_context(run_id=None, trace_id="trace-chat-start")
    repository = InMemorySessionRepository()
    task = ClarifiedTask(
        intent="collect products",
        list_url="https://example.com/list",
        task_description="collect product cards",
        fields=(RequestedField(name="title", description="product title"),),
    )
    clarifier = StubClarifier(
        ClarificationResult(
            status="ready",
            intent="collect products",
            confidence=0.9,
            next_question="",
            reason="",
            task=task,
        )
    )

    use_case = StartClarification(repository, clarifier)
    result = await use_case.run(StartClarificationInput(initial_request="抓取商品标题"))

    assert result.status == "success"
    assert result.data is not None
    assert result.data.status == "finalized"
    assert result.data.result.task is not None
    assert result.data.result.task.fields[0].name == "title"
    assert clarifier.calls[0]["available_skills"] == []
    clear_run_context()


@pytest.mark.asyncio
async def test_advance_dialogue_appends_assistant_question() -> None:
    set_run_context(run_id=None, trace_id="trace-chat-advance")
    repository = InMemorySessionRepository()
    session = ClarificationSession(
        session_id="session-1",
        turns=(DialogueMessage(role="user", content="先帮我看网站"),),
    )
    await repository.save(session)
    clarifier = StubClarifier(
        ClarificationResult(
            status="need_clarification",
            intent="",
            confidence=0.4,
            next_question="请提供列表页 URL。",
            reason="",
            task=None,
        )
    )

    use_case = AdvanceDialogue(repository, clarifier)
    result = await use_case.run(
        AdvanceDialogueInput(session_id="session-1", user_message="我想抓商品信息")
    )

    assert result.status == "success"
    assert result.data is not None
    assert result.data.status == "ongoing"
    assert result.data.turns[-1].role == "assistant"
    assert result.data.turns[-1].content == "请提供列表页 URL。"
    clear_run_context()


@pytest.mark.asyncio
async def test_use_cases_forward_selected_skills_context() -> None:
    set_run_context(run_id=None, trace_id="trace-chat-skills")
    repository = InMemorySessionRepository()
    clarifier = StubClarifier(
        ClarificationResult(
            status="need_clarification",
            intent="collect products",
            confidence=0.5,
            next_question="请确认字段。",
            reason="",
            task=None,
        )
    )

    use_case = StartClarification(repository, clarifier)
    await use_case.run(
        StartClarificationInput(
            initial_request="抓取商品标题",
            available_skills=[{"name": "catalog", "path": "skills/catalog"}],
            selected_skills=[{"name": "catalog", "path": "skills/catalog"}],
            selected_skills_context="catalog skill body",
        )
    )

    assert clarifier.calls[0]["available_skills"] == [{"name": "catalog", "path": "skills/catalog"}]
    assert clarifier.calls[0]["selected_skills"] == [{"name": "catalog", "path": "skills/catalog"}]
    assert clarifier.calls[0]["selected_skills_context"] == "catalog skill body"
    clear_run_context()

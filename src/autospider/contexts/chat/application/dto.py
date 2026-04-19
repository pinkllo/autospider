from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from autospider.contexts.chat.domain.model import (
    ClarificationResult,
    ClarificationSession,
    ClarifiedTask,
    DialogueMessage,
    RequestedField,
)


class StartClarificationInput(BaseModel):
    initial_request: str
    available_skills: list[dict[str, str]] = Field(default_factory=list)
    selected_skills: list[dict[str, str]] = Field(default_factory=list)
    selected_skills_context: str = ""


class AdvanceDialogueInput(BaseModel):
    session_id: str
    user_message: str
    available_skills: list[dict[str, str]] = Field(default_factory=list)
    selected_skills: list[dict[str, str]] = Field(default_factory=list)
    selected_skills_context: str = ""


class FinalizeTaskInput(BaseModel):
    session_id: str


class RequestedFieldDTO(BaseModel):
    name: str
    description: str
    required: bool
    data_type: str
    example: str | None = None


class DialogueMessageDTO(BaseModel):
    role: str
    content: str


class ClarifiedTaskDTO(BaseModel):
    intent: str
    list_url: str
    task_description: str
    fields: list[RequestedFieldDTO] = Field(default_factory=list)
    group_by: str
    per_group_target_count: int | None = None
    total_target_count: int | None = None
    category_discovery_mode: str
    requested_categories: list[str] = Field(default_factory=list)
    category_examples: list[str] = Field(default_factory=list)
    max_pages: int | None = None
    target_url_count: int | None = None
    consumer_concurrency: int | None = None
    field_explore_count: int | None = None
    field_validate_count: int | None = None


class ClarificationResultDTO(BaseModel):
    status: Literal["need_clarification", "ready", "reject"]
    intent: str
    confidence: float
    next_question: str
    reason: str
    task: ClarifiedTaskDTO | None = None


class ClarificationSessionDTO(BaseModel):
    session_id: str
    status: str
    turns: list[DialogueMessageDTO] = Field(default_factory=list)
    result: ClarificationResultDTO


def to_field_dto(field: RequestedField) -> RequestedFieldDTO:
    return RequestedFieldDTO(**field.to_payload())


def to_message_dto(message: DialogueMessage) -> DialogueMessageDTO:
    return DialogueMessageDTO(**message.to_payload())


def to_task_dto(task: ClarifiedTask) -> ClarifiedTaskDTO:
    payload = task.to_payload()
    payload["fields"] = [to_field_dto(field) for field in task.fields]
    return ClarifiedTaskDTO(**payload)


def to_result_dto(result: ClarificationResult) -> ClarificationResultDTO:
    task = None if result.task is None else to_task_dto(result.task)
    return ClarificationResultDTO(
        status=result.status,
        intent=result.intent,
        confidence=result.confidence,
        next_question=result.next_question,
        reason=result.reason,
        task=task,
    )


def to_session_dto(
    session: ClarificationSession,
    result: ClarificationResult,
) -> ClarificationSessionDTO:
    turns = [to_message_dto(message) for message in session.turns]
    return ClarificationSessionDTO(
        session_id=session.session_id,
        status=session.status,
        turns=turns,
        result=to_result_dto(result),
    )

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DecisionStatus = Literal["need_clarification", "ready", "reject"]
SessionStatus = Literal["ongoing", "finalized", "abandoned"]


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class DialogueMessage:
    role: str
    content: str

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "DialogueMessage":
        return cls(role=_text(payload.get("role")), content=_text(payload.get("content")))

    def to_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class RequestedField:
    name: str
    description: str
    required: bool = True
    data_type: str = "text"
    example: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "RequestedField":
        example = payload.get("example")
        normalized_example = None if example is None else _text(example) or None
        return cls(
            name=_text(payload.get("name")),
            description=_text(payload.get("description")),
            required=bool(payload.get("required", True)),
            data_type=_text(payload.get("data_type")) or "text",
            example=normalized_example,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "data_type": self.data_type,
            "example": self.example,
        }


@dataclass(frozen=True, slots=True)
class ClarifiedTask:
    intent: str
    list_url: str
    task_description: str
    fields: tuple[RequestedField, ...]
    group_by: str = "none"
    per_group_target_count: int | None = None
    total_target_count: int | None = None
    category_discovery_mode: str = "auto"
    requested_categories: tuple[str, ...] = ()
    category_examples: tuple[str, ...] = ()
    max_pages: int | None = None
    target_url_count: int | None = None
    consumer_concurrency: int | None = None
    field_explore_count: int | None = None
    field_validate_count: int | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ClarifiedTask":
        fields = tuple(
            RequestedField.from_mapping(item)
            for item in list(payload.get("fields") or [])
            if isinstance(item, dict)
        )
        return cls(
            intent=_text(payload.get("intent")),
            list_url=_text(payload.get("list_url")),
            task_description=_text(payload.get("task_description")),
            fields=fields,
            group_by=_text(payload.get("group_by")) or "none",
            per_group_target_count=payload.get("per_group_target_count"),
            total_target_count=payload.get("total_target_count"),
            category_discovery_mode=_text(payload.get("category_discovery_mode")) or "auto",
            requested_categories=tuple(_text(item) for item in list(payload.get("requested_categories") or [])),
            category_examples=tuple(_text(item) for item in list(payload.get("category_examples") or [])),
            max_pages=payload.get("max_pages"),
            target_url_count=payload.get("target_url_count"),
            consumer_concurrency=payload.get("consumer_concurrency"),
            field_explore_count=payload.get("field_explore_count"),
            field_validate_count=payload.get("field_validate_count"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "list_url": self.list_url,
            "task_description": self.task_description,
            "fields": [field.to_payload() for field in self.fields],
            "group_by": self.group_by,
            "per_group_target_count": self.per_group_target_count,
            "total_target_count": self.total_target_count,
            "category_discovery_mode": self.category_discovery_mode,
            "requested_categories": list(self.requested_categories),
            "category_examples": list(self.category_examples),
            "max_pages": self.max_pages,
            "target_url_count": self.target_url_count,
            "consumer_concurrency": self.consumer_concurrency,
            "field_explore_count": self.field_explore_count,
            "field_validate_count": self.field_validate_count,
        }


@dataclass(frozen=True, slots=True)
class ClarificationResult:
    status: DecisionStatus
    intent: str
    confidence: float
    next_question: str
    reason: str
    task: ClarifiedTask | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "intent": self.intent,
            "confidence": self.confidence,
            "next_question": self.next_question,
            "reason": self.reason,
        }
        payload["task"] = None if self.task is None else self.task.to_payload()
        return payload


@dataclass(frozen=True, slots=True)
class ClarificationSession:
    session_id: str
    status: SessionStatus = "ongoing"
    turns: tuple[DialogueMessage, ...] = field(default_factory=tuple)
    clarified_task: ClarifiedTask | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "session_id": self.session_id,
            "status": self.status,
            "turns": [turn.to_payload() for turn in self.turns],
        }
        payload["clarified_task"] = (
            None if self.clarified_task is None else self.clarified_task.to_payload()
        )
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClarificationSession":
        turns = tuple(
            DialogueMessage.from_mapping(item)
            for item in list(payload.get("turns") or [])
            if isinstance(item, dict)
        )
        raw_task = payload.get("clarified_task")
        clarified_task = None
        if isinstance(raw_task, dict):
            clarified_task = ClarifiedTask.from_mapping(raw_task)
        return cls(
            session_id=_text(payload.get("session_id")),
            status=_text(payload.get("status")) or "ongoing",
            turns=turns,
            clarified_task=clarified_task,
        )

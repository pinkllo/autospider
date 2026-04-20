"""Shared contracts for validating LLM outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .grouping_semantics import (
    normalize_grouping_semantics,
    normalize_positive_int,
    normalize_string_list,
)

_PROTOCOL_ACTIONS = (
    "click",
    "type",
    "scroll",
    "navigate",
    "wait",
    "extract",
    "go_back",
    "go_back_tab",
    "done",
    "retry",
    "select",
    "report",
)
_STATUS_VALUES = ("need_clarification", "ready", "reject")
_FIELD_TYPES = ("text", "number", "date", "url")


def _strip_text(value: Any) -> str:
    return str(value or "").strip()


def _strip_optional_text(value: Any) -> str | None:
    text = _strip_text(value)
    return text or None


def _format_validation_errors(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg") or "invalid")
        messages.append(f"{location}: {message}" if location else message)
    return messages


class ClarifierFieldPayload(BaseModel):
    """Strict payload for one clarified field."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    description: str = ""
    required: bool = True
    data_type: Literal["text", "number", "date", "url"] = "text"
    example: str | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: Any) -> str:
        return _strip_text(value)

    @field_validator("example", mode="before")
    @classmethod
    def _normalize_example(cls, value: Any) -> str | None:
        return _strip_optional_text(value)

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "ClarifierFieldPayload":
        if not self.name:
            raise ValueError("field name cannot be empty")
        if not self.description:
            raise ValueError("field description cannot be empty")
        return self


class TaskClarifierPayload(BaseModel):
    """Strict payload for task clarifier output."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["need_clarification", "ready", "reject"] = "need_clarification"
    intent: str = ""
    confidence: float = 0.0
    next_question: str = ""
    task_description: str = ""
    list_url: str = ""
    fields: list[ClarifierFieldPayload] = Field(default_factory=list)
    group_by: Literal["none", "category"] = "none"
    per_group_target_count: int | None = None
    total_target_count: int | None = None
    category_discovery_mode: Literal["auto", "manual"] = "auto"
    requested_categories: list[str] = Field(default_factory=list)
    category_examples: list[str] = Field(default_factory=list)
    max_pages: int | None = None
    target_url_count: int | None = None
    consumer_concurrency: int | None = None
    field_explore_count: int | None = None
    field_validate_count: int | None = None
    rejection_reason: str = ""

    @field_validator(
        "intent",
        "next_question",
        "task_description",
        "list_url",
        "rejection_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _strip_text(value)

    @field_validator(
        "requested_categories",
        "category_examples",
        mode="before",
    )
    @classmethod
    def _normalize_list_fields(cls, value: Any) -> list[str]:
        return normalize_string_list(value)

    @field_validator(
        "per_group_target_count",
        "total_target_count",
        "max_pages",
        "target_url_count",
        "consumer_concurrency",
        "field_explore_count",
        "field_validate_count",
        mode="before",
    )
    @classmethod
    def _normalize_int_fields(cls, value: Any) -> int | None:
        return normalize_positive_int(value)

    @model_validator(mode="after")
    def _normalize_grouping_semantics(self) -> "TaskClarifierPayload":
        normalized = normalize_grouping_semantics(self.model_dump(mode="python"))
        self.group_by = normalized["group_by"]
        self.per_group_target_count = normalized["per_group_target_count"]
        self.total_target_count = normalized["total_target_count"]
        self.category_discovery_mode = normalized["category_discovery_mode"]
        self.requested_categories = normalized["requested_categories"]
        self.category_examples = normalized["category_examples"]
        return self


class ProtocolArgsPayload(BaseModel):
    """Protocol args with light structural validation."""

    model_config = ConfigDict(extra="allow")

    kind: Any = None
    purpose: Any = None
    page_kind: Any = None
    target_text: Any = None
    text: Any = None
    key: Any = None
    url: Any = None
    reasoning: Any = None
    summary: Any = None
    found: Any = None
    mark_id: Any = None
    selected_mark_id: Any = None
    items: Any = None
    input: Any = None
    button: Any = None
    scroll_delta: Any = None
    field_name: Any = None
    field_text: Any = None
    field_value: Any = None
    location_description: Any = None
    confidence: Any = None
    timeout_ms: Any = None
    expectation: Any = None

    @field_validator(
        "kind",
        "purpose",
        "page_kind",
        "target_text",
        "text",
        "key",
        "url",
        "reasoning",
        "summary",
        "field_name",
        "field_text",
        "field_value",
        "location_description",
        "expectation",
        mode="before",
    )
    @classmethod
    def _normalize_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("scroll_delta", mode="before")
    @classmethod
    def _normalize_scroll_delta(cls, value: Any) -> list[int] | None:
        if value is None:
            return None
        if isinstance(value, tuple):
            value = list(value)
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("scroll_delta must be a 2-item list")
        return [int(value[0]), int(value[1])]

    def to_payload(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        if "scroll_delta" in payload and isinstance(payload["scroll_delta"], tuple):
            payload["scroll_delta"] = list(payload["scroll_delta"])
        return payload


class ProtocolMessagePayload(BaseModel):
    """Strict payload for action protocol messages."""

    model_config = ConfigDict(extra="ignore")

    action: Literal[
        "click",
        "type",
        "scroll",
        "navigate",
        "wait",
        "extract",
        "go_back",
        "go_back_tab",
        "done",
        "retry",
        "select",
        "report",
    ]
    args: ProtocolArgsPayload = Field(default_factory=ProtocolArgsPayload)
    thinking: str = ""

    @field_validator("thinking", mode="before")
    @classmethod
    def _normalize_thinking(cls, value: Any) -> str:
        return _strip_text(value)

    @model_validator(mode="after")
    def _validate_action_args(self) -> "ProtocolMessagePayload":
        if self.action == "click" and not (self.args.target_text or self.args.mark_id is not None):
            raise ValueError("click requires target_text or mark_id")
        if self.action == "type" and not self.args.text:
            raise ValueError("type requires text")
        if self.action == "type" and not (self.args.target_text or self.args.mark_id is not None):
            raise ValueError("type requires target_text or mark_id")
        if self.action == "scroll" and self.args.scroll_delta is None:
            raise ValueError("scroll requires scroll_delta")
        if self.action == "navigate" and not self.args.url:
            raise ValueError("navigate requires url")
        return self

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "action": self.action,
            "args": self.args.to_payload(),
        }
        if self.thinking:
            payload["thinking"] = self.thinking
        return payload


def validate_task_clarifier_payload(raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Validate and normalize task clarifier JSON payload."""
    try:
        payload = TaskClarifierPayload.model_validate(dict(raw or {}))
    except ValidationError as exc:
        return {}, _format_validation_errors(exc)
    return payload.model_dump(mode="python"), []


def validate_protocol_message_payload(
    *,
    action: str,
    args: dict[str, Any] | None,
    thinking: str = "",
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate and normalize protocol message payload."""
    try:
        payload = ProtocolMessagePayload.model_validate(
            {
                "action": _strip_text(action).lower(),
                "args": dict(args or {}),
                "thinking": thinking,
            }
        )
    except ValidationError as exc:
        return None, _format_validation_errors(exc)
    return payload.to_payload(), []

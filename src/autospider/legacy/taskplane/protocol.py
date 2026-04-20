"""Protocol layer: core data models and state machine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_TRANSITIONS: dict[str, set[str]] = {
    "registered": {"queued", "cancelled"},
    "queued": {"dispatched", "cancelled"},
    "dispatched": {"running", "timeout", "cancelled"},
    "running": {"completed", "failed", "expanded"},
    "timeout": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "completed": set(),
    "expanded": set(),
    "cancelled": set(),
}
_TERMINAL: set[str] = {"completed", "failed", "expanded", "cancelled"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TicketStatus(str, Enum):
    REGISTERED = "registered"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPANDED = "expanded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self.value in _TERMINAL

    def can_transition_to(self, target: "TicketStatus") -> bool:
        return target.value in _TRANSITIONS.get(self.value, set())


class ResultStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    EXPANDED = "expanded"


class TaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result_id: str
    ticket_id: str
    status: ResultStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    spawned_tickets: list[dict[str, Any]] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=_utcnow)


class TaskTicket(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    envelope_id: str
    parent_ticket_id: str | None = None
    status: TicketStatus = TicketStatus.REGISTERED
    priority: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    assigned_to: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    attempt_count: int = 0
    max_attempts: int = 3
    timeout_seconds: int | None = None
    result: TaskResult | None = None


class PlanEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    envelope_id: str
    source_agent: str
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tickets: list[TaskTicket] = Field(default_factory=list)
    plan_snapshot: dict[str, Any] = Field(default_factory=dict)

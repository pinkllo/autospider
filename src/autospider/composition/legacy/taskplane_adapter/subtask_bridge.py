"""Convert SubTask ↔ TaskTicket."""

from __future__ import annotations

from autospider.contexts.planning.domain import SubTask
from ..taskplane.protocol import TaskTicket


class SubtaskBridge:
    @staticmethod
    def to_ticket(subtask: SubTask, *, envelope_id: str) -> TaskTicket:
        labels = {"mode": subtask.mode.value, "depth": str(subtask.depth)}
        scope = dict(subtask.scope or {})
        if scope.get("key"):
            labels["scope_key"] = str(scope["key"])
        return TaskTicket(
            ticket_id=subtask.id,
            envelope_id=envelope_id,
            parent_ticket_id=subtask.parent_id,
            priority=subtask.priority,
            payload=subtask.model_dump(mode="python"),
            labels=labels,
        )

    @staticmethod
    def from_ticket(ticket: TaskTicket) -> SubTask:
        return SubTask.model_validate(ticket.payload)

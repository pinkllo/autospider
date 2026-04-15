"""TaskStore protocol — all backends must implement this interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus


@runtime_checkable
class TaskStore(Protocol):
    async def save_envelope(self, envelope: PlanEnvelope) -> None:
        ...

    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None:
        ...

    async def save_ticket(self, ticket: TaskTicket) -> None:
        ...

    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None:
        ...

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        ...

    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]:
        ...

    async def update_status(
        self,
        ticket_id: str,
        status: TicketStatus,
        **kwargs: Any,
    ) -> TaskTicket:
        ...

    async def claim_next(
        self,
        labels: dict[str, str] | None = None,
        batch_size: int = 1,
    ) -> list[TaskTicket]:
        ...

    async def release_claim(self, ticket_id: str, reason: str) -> None:
        ...

    async def save_result(self, result: TaskResult) -> None:
        ...

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        ...

    async def query_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]:
        ...

"""In-memory TaskStore for tests and fallback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus
from ..strategy import DispatchStrategy, PriorityStrategy


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    def __init__(self, *, strategy: DispatchStrategy | None = None) -> None:
        self._strategy = strategy or PriorityStrategy()
        self._envelopes: dict[str, PlanEnvelope] = {}
        self._tickets: dict[str, TaskTicket] = {}
        self._results: dict[str, TaskResult] = {}

    async def aclose(self) -> None:
        return None

    async def save_envelope(self, envelope: PlanEnvelope) -> None:
        self._envelopes[envelope.envelope_id] = envelope.model_copy(deep=True)

    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None:
        envelope = self._envelopes.get(envelope_id)
        return None if envelope is None else envelope.model_copy(deep=True)

    async def save_ticket(self, ticket: TaskTicket) -> None:
        self._tickets[ticket.ticket_id] = ticket.model_copy(deep=True)

    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None:
        for ticket in tickets:
            await self.save_ticket(ticket)

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        ticket = self._tickets.get(ticket_id)
        return None if ticket is None else ticket.model_copy(deep=True)

    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]:
        tickets = [ticket for ticket in self._tickets.values() if ticket.envelope_id == envelope_id]
        return [ticket.model_copy(deep=True) for ticket in tickets]

    async def update_status(
        self,
        ticket_id: str,
        status: TicketStatus,
        **kwargs: Any,
    ) -> TaskTicket:
        ticket = self._tickets[ticket_id]
        updates = {"status": status, "updated_at": _utcnow(), **kwargs}
        updated = ticket.model_copy(update=updates)
        self._tickets[ticket_id] = updated
        return updated.model_copy(deep=True)

    async def claim_next(
        self,
        labels: dict[str, str] | None = None,
        batch_size: int = 1,
    ) -> list[TaskTicket]:
        candidates = [
            ticket
            for ticket in self._tickets.values()
            if ticket.status == TicketStatus.QUEUED and self._matches_labels(ticket, labels)
        ]
        candidates.sort(key=self._strategy.compute_score)
        claimed: list[TaskTicket] = []
        for ticket in candidates[: max(batch_size, 0)]:
            claimed.append(await self.update_status(ticket.ticket_id, TicketStatus.DISPATCHED))
        return claimed

    async def release_claim(self, ticket_id: str, reason: str) -> None:
        await self.update_status(ticket_id, TicketStatus.QUEUED, assigned_to=None)

    async def save_result(self, result: TaskResult) -> None:
        stored_result = result.model_copy(deep=True)
        self._results[result.ticket_id] = stored_result
        ticket = self._tickets.get(result.ticket_id)
        if ticket is None:
            return
        self._tickets[result.ticket_id] = ticket.model_copy(
            update={"result": stored_result, "updated_at": result.completed_at}
        )

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        result = self._results.get(ticket_id)
        return None if result is None else result.model_copy(deep=True)

    async def query_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]:
        tickets: list[TaskTicket] = []
        for ticket in self._tickets.values():
            if status is not None and ticket.status != status:
                continue
            if envelope_id is not None and ticket.envelope_id != envelope_id:
                continue
            if not self._matches_labels(ticket, labels):
                continue
            tickets.append(ticket.model_copy(deep=True))
            if len(tickets) >= limit:
                break
        return tickets

    @staticmethod
    def _matches_labels(ticket: TaskTicket, labels: dict[str, str] | None) -> bool:
        if labels is None:
            return True
        return all(ticket.labels.get(key) == value for key, value in labels.items())

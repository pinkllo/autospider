"""TaskScheduler — main entry point for the TaskPlane module."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from .protocol import PlanEnvelope, ResultStatus, TaskResult, TaskTicket, TicketStatus
from .store.base import TaskStore
from .strategy import DispatchStrategy, PriorityStrategy
from .types import EnvelopeProgress, ReportReceipt, SubmitReceipt

if TYPE_CHECKING:
    from .subscription import Subscription

_TERMINAL_PROGRESS_FIELDS = (
    "completed",
    "failed",
    "expanded",
    "cancelled",
)


class TaskScheduler:
    def __init__(
        self,
        store: TaskStore,
        *,
        dispatch_strategy: DispatchStrategy | None = None,
        on_ticket_complete: Callable[[TaskTicket, TaskResult], Awaitable[None]] | None = None,
        on_ticket_failed: Callable[[TaskTicket, str], Awaitable[None]] | None = None,
        on_envelope_complete: Callable[[PlanEnvelope], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._strategy = dispatch_strategy or PriorityStrategy()
        self._on_ticket_complete = on_ticket_complete
        self._on_ticket_failed = on_ticket_failed
        self._on_envelope_complete = on_envelope_complete
        self._completed_envelopes: set[str] = set()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._completed_envelopes.clear()
        await self._store.aclose()

    async def submit_envelope(self, envelope: PlanEnvelope) -> SubmitReceipt:
        self._ensure_open()
        await self._store.save_envelope(envelope)
        queued_tickets = [
            self._queue_ticket(ticket, envelope.envelope_id) for ticket in envelope.tickets
        ]
        await self._store.save_tickets_batch(queued_tickets)
        return SubmitReceipt(envelope_id=envelope.envelope_id, ticket_count=len(queued_tickets))

    async def submit_tickets(self, envelope_id: str, tickets: list[TaskTicket]) -> list[str]:
        self._ensure_open()
        queued_tickets = [self._queue_ticket(ticket, envelope_id) for ticket in tickets]
        await self._store.save_tickets_batch(queued_tickets)
        self._completed_envelopes.discard(envelope_id)
        return [ticket.ticket_id for ticket in queued_tickets]

    async def cancel_ticket(self, ticket_id: str, reason: str = "") -> None:
        self._ensure_open()
        ticket = await self._store.get_ticket(ticket_id)
        if ticket is None or ticket.status.is_terminal:
            return
        cancelled = await self._store.update_status(
            ticket_id, TicketStatus.CANCELLED, assigned_to=None
        )
        await self._notify_envelope_complete(cancelled.envelope_id)

    async def cancel_envelope(self, envelope_id: str, reason: str = "") -> None:
        self._ensure_open()
        tickets = await self._store.get_tickets_by_envelope(envelope_id)
        for ticket in tickets:
            if ticket.status.is_terminal:
                continue
            await self._store.update_status(
                ticket.ticket_id,
                TicketStatus.CANCELLED,
                assigned_to=None,
            )
        await self._notify_envelope_complete(envelope_id)

    async def pull(
        self,
        *,
        labels: dict[str, str] | None = None,
        batch_size: int = 1,
    ) -> list[TaskTicket]:
        self._ensure_open()
        return await self._store.claim_next(labels=labels, batch_size=batch_size)

    async def ack_start(self, ticket_id: str, agent_id: str = "") -> None:
        self._ensure_open()
        updates: dict[str, Any] = {"assigned_to": agent_id or None}
        await self._store.update_status(ticket_id, TicketStatus.RUNNING, **updates)

    async def report_result(self, result: TaskResult) -> ReportReceipt:
        self._ensure_open()
        await self._store.save_result(result)
        ticket = await self._store.get_ticket(result.ticket_id)
        if ticket is None:
            raise ValueError(f"unknown_ticket: {result.ticket_id}")

        if result.status == ResultStatus.SUCCESS:
            return await self._handle_success(ticket, result)
        if result.status == ResultStatus.EXPANDED:
            return await self._handle_expanded(ticket, result)
        return await self._handle_failure(ticket, result)

    async def heartbeat(self, ticket_id: str) -> None:
        self._ensure_open()
        return None

    async def release(self, ticket_id: str, reason: str = "") -> None:
        self._ensure_open()
        await self._store.release_claim(ticket_id, reason)

    def subscribe(
        self,
        handler: Callable[[TaskTicket], Awaitable[TaskResult]],
        *,
        labels: dict[str, str] | None = None,
        concurrency: int = 1,
    ) -> "Subscription":
        self._ensure_open()
        from .subscription import Subscription

        return Subscription(
            scheduler=self,
            handler=handler,
            labels=labels,
            concurrency=concurrency,
        )

    async def get_envelope_progress(self, envelope_id: str) -> EnvelopeProgress:
        self._ensure_open()
        tickets = await self._store.get_tickets_by_envelope(envelope_id)
        counts = {status.value: 0 for status in TicketStatus}
        for ticket in tickets:
            counts[ticket.status.value] += 1
        return EnvelopeProgress(
            envelope_id=envelope_id,
            total=len(tickets),
            queued=counts["queued"],
            dispatched=counts["dispatched"],
            running=counts["running"],
            completed=counts["completed"],
            failed=counts["failed"],
            expanded=counts["expanded"],
            cancelled=counts["cancelled"],
        )

    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None:
        self._ensure_open()
        return await self._store.get_envelope(envelope_id)

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        self._ensure_open()
        return await self._store.get_ticket(ticket_id)

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        self._ensure_open()
        return await self._store.get_result(ticket_id)

    def _queue_ticket(self, ticket: TaskTicket, envelope_id: str) -> TaskTicket:
        return ticket.model_copy(
            update={
                "envelope_id": envelope_id,
                "status": TicketStatus.QUEUED,
                "assigned_to": None,
            }
        )

    async def _handle_success(self, ticket: TaskTicket, result: TaskResult) -> ReportReceipt:
        updated = await self._store.update_status(
            ticket.ticket_id,
            TicketStatus.COMPLETED,
            assigned_to=ticket.assigned_to,
        )
        if self._on_ticket_complete is not None:
            await self._on_ticket_complete(updated, result)
        await self._notify_envelope_complete(updated.envelope_id)
        return ReportReceipt(
            ticket_id=ticket.ticket_id,
            final_status=TicketStatus.COMPLETED,
            retried=False,
            spawned_count=0,
        )

    async def _handle_expanded(self, ticket: TaskTicket, result: TaskResult) -> ReportReceipt:
        updated = await self._store.update_status(
            ticket.ticket_id,
            TicketStatus.EXPANDED,
            assigned_to=ticket.assigned_to,
        )
        spawned_tickets = [
            TaskTicket.model_validate(
                {"envelope_id": ticket.envelope_id, "parent_ticket_id": ticket.ticket_id, **raw}
            )
            for raw in result.spawned_tickets
        ]
        if spawned_tickets:
            await self.submit_tickets(ticket.envelope_id, spawned_tickets)
        await self._notify_envelope_complete(updated.envelope_id)
        return ReportReceipt(
            ticket_id=ticket.ticket_id,
            final_status=TicketStatus.EXPANDED,
            retried=False,
            spawned_count=len(spawned_tickets),
        )

    async def _handle_failure(self, ticket: TaskTicket, result: TaskResult) -> ReportReceipt:
        attempt_count = ticket.attempt_count + 1
        if attempt_count < ticket.max_attempts:
            await self._store.update_status(
                ticket.ticket_id,
                TicketStatus.FAILED,
                attempt_count=attempt_count,
                assigned_to=None,
            )
            await self._store.update_status(
                ticket.ticket_id,
                TicketStatus.QUEUED,
                attempt_count=attempt_count,
                assigned_to=None,
            )
            return ReportReceipt(
                ticket_id=ticket.ticket_id,
                final_status=TicketStatus.QUEUED,
                retried=True,
                spawned_count=0,
            )
        updated = await self._store.update_status(
            ticket.ticket_id,
            TicketStatus.FAILED,
            attempt_count=attempt_count,
            assigned_to=None,
        )
        if self._on_ticket_failed is not None:
            await self._on_ticket_failed(updated, result.error)
        await self._notify_envelope_complete(updated.envelope_id)
        return ReportReceipt(
            ticket_id=ticket.ticket_id,
            final_status=TicketStatus.FAILED,
            retried=False,
            spawned_count=0,
        )

    async def _notify_envelope_complete(self, envelope_id: str) -> None:
        if self._on_envelope_complete is None or envelope_id in self._completed_envelopes:
            return
        progress = await self.get_envelope_progress(envelope_id)
        terminal_total = sum(getattr(progress, field) for field in _TERMINAL_PROGRESS_FIELDS)
        if progress.total == 0 or terminal_total != progress.total:
            return
        envelope = await self._store.get_envelope(envelope_id)
        if envelope is None:
            return
        self._completed_envelopes.add(envelope_id)
        await self._on_envelope_complete(envelope)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("task_scheduler_closed")

"""Dual-layer store combining Redis hot data and PostgreSQL cold durability."""

from __future__ import annotations

import asyncio
from typing import Any

from ..protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus
from .base import TaskStore


class DualLayerStore:
    def __init__(self, *, hot_store: TaskStore, cold_store: TaskStore) -> None:
        self._hot_store = hot_store
        self._cold_store = cold_store
        self._pending_writes: set[asyncio.Task[None]] = set()
        self._background_error: Exception | None = None

    async def save_envelope(self, envelope: PlanEnvelope) -> None:
        self._raise_if_background_failed()
        await self._hot_store.save_envelope(envelope)
        await self._cold_store.save_envelope(envelope)

    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None:
        self._raise_if_background_failed()
        envelope = await self._hot_store.get_envelope(envelope_id)
        if envelope is not None:
            return envelope
        envelope = await self._cold_store.get_envelope(envelope_id)
        if envelope is not None:
            await self._hot_store.save_envelope(envelope)
        return envelope

    async def save_ticket(self, ticket: TaskTicket) -> None:
        self._raise_if_background_failed()
        await self._hot_store.save_ticket(ticket)
        self._schedule_cold_write("save_ticket", ticket)

    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None:
        self._raise_if_background_failed()
        await self._hot_store.save_tickets_batch(tickets)
        self._schedule_cold_write("save_tickets_batch", tickets)

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        self._raise_if_background_failed()
        ticket = await self._hot_store.get_ticket(ticket_id)
        if ticket is not None:
            return ticket
        ticket = await self._cold_store.get_ticket(ticket_id)
        if ticket is not None:
            await self._hot_store.save_ticket(ticket)
            if ticket.result is not None:
                await self._hot_store.save_result(ticket.result)
        return ticket

    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]:
        self._raise_if_background_failed()
        return await self._cold_store.get_tickets_by_envelope(envelope_id)

    async def update_status(
        self,
        ticket_id: str,
        status: TicketStatus,
        **kwargs: Any,
    ) -> TaskTicket:
        self._raise_if_background_failed()
        updated = await self._hot_store.update_status(ticket_id, status, **kwargs)
        self._schedule_cold_write("update_status", ticket_id, status, **kwargs)
        return updated

    async def claim_next(
        self,
        labels: dict[str, str] | None = None,
        batch_size: int = 1,
    ) -> list[TaskTicket]:
        self._raise_if_background_failed()
        return await self._hot_store.claim_next(labels=labels, batch_size=batch_size)

    async def release_claim(self, ticket_id: str, reason: str) -> None:
        self._raise_if_background_failed()
        await self._hot_store.release_claim(ticket_id, reason)
        self._schedule_cold_write("release_claim", ticket_id, reason)

    async def save_result(self, result: TaskResult) -> None:
        self._raise_if_background_failed()
        await self._hot_store.save_result(result)
        await self._cold_store.save_result(result)

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        self._raise_if_background_failed()
        result = await self._cold_store.get_result(ticket_id)
        if result is not None:
            return result
        return await self._hot_store.get_result(ticket_id)

    async def query_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]:
        self._raise_if_background_failed()
        return await self._cold_store.query_tickets(
            status=status,
            envelope_id=envelope_id,
            labels=labels,
            limit=limit,
        )

    async def aclose(self) -> None:
        await self._drain_pending_writes()
        await self._close_store(self._hot_store)
        await self._close_store(self._cold_store)
        self._raise_if_background_failed()

    async def _drain_pending_writes(self) -> None:
        if not self._pending_writes:
            return
        await asyncio.gather(*list(self._pending_writes), return_exceptions=True)

    async def _close_store(self, store: TaskStore) -> None:
        closer = getattr(store, "aclose", None)
        if closer is not None:
            await closer()

    def _schedule_cold_write(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        task = asyncio.create_task(self._run_cold_write(method_name, *args, **kwargs))
        self._pending_writes.add(task)
        task.add_done_callback(self._capture_background_result)

    async def _run_cold_write(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        method = getattr(self._cold_store, method_name)
        await method(*args, **kwargs)

    def _capture_background_result(self, task: asyncio.Task[None]) -> None:
        self._pending_writes.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is None or self._background_error is not None:
            return
        wrapped = RuntimeError("dual_layer_store_background_write_failed")
        wrapped.__cause__ = error
        self._background_error = wrapped

    def _raise_if_background_failed(self) -> None:
        if self._background_error is not None:
            raise self._background_error

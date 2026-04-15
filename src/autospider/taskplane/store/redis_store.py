"""Redis-backed hot store for active TaskPlane tickets."""

from __future__ import annotations

import json
from typing import Any

from ..protocol import PlanEnvelope, TaskResult, TaskTicket, TicketStatus
from ..strategy import DispatchStrategy, PriorityStrategy
from ._model_codec import decode_model, encode_model, utcnow

_DEFAULT_CLAIM_TTL_SECONDS = 600


class RedisHotStore:
    def __init__(
        self,
        *,
        redis_url: str,
        namespace: str = "taskplane",
        strategy: DispatchStrategy | None = None,
        terminal_ttl_seconds: int = 3600,
        default_claim_ttl_seconds: int = _DEFAULT_CLAIM_TTL_SECONDS,
    ) -> None:
        self._redis_url = redis_url
        self._namespace = namespace.strip() or "taskplane"
        self._strategy = strategy or PriorityStrategy()
        self._terminal_ttl_seconds = terminal_ttl_seconds
        self._default_claim_ttl_seconds = default_claim_ttl_seconds
        self._redis = None

    async def save_envelope(self, envelope: PlanEnvelope) -> None:
        client = self._client()
        await client.hset(self._envelope_key(envelope.envelope_id), mapping={"blob": encode_model(envelope)})

    async def get_envelope(self, envelope_id: str) -> PlanEnvelope | None:
        client = self._client()
        raw = await client.hget(self._envelope_key(envelope_id), "blob")
        return decode_model(PlanEnvelope, raw)

    async def save_ticket(self, ticket: TaskTicket) -> None:
        await self._write_ticket(ticket)

    async def save_tickets_batch(self, tickets: list[TaskTicket]) -> None:
        for ticket in tickets:
            await self._write_ticket(ticket)

    async def get_ticket(self, ticket_id: str) -> TaskTicket | None:
        client = self._client()
        raw = await client.hget(self._ticket_key(ticket_id), "blob")
        ticket = decode_model(TaskTicket, raw)
        if ticket is None:
            return None
        result = await self.get_result(ticket_id)
        if result is None:
            return ticket
        return ticket.model_copy(update={"result": result})

    async def get_tickets_by_envelope(self, envelope_id: str) -> list[TaskTicket]:
        client = self._client()
        ticket_ids = sorted(await client.smembers(self._envelope_tickets_key(envelope_id)))
        return await self._load_tickets(ticket_ids)

    async def update_status(
        self,
        ticket_id: str,
        status: TicketStatus,
        **kwargs: Any,
    ) -> TaskTicket:
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            raise ValueError(f"unknown_ticket: {ticket_id}")
        updates = {"status": status, "updated_at": utcnow(), **kwargs}
        updated = ticket.model_copy(update=updates)
        await self._write_ticket(updated)
        await self._sync_claim_lock(updated)
        return updated

    async def claim_next(
        self,
        labels: dict[str, str] | None = None,
        batch_size: int = 1,
    ) -> list[TaskTicket]:
        client = self._client()
        queue_key = self._queue_key(labels)
        claimed: list[TaskTicket] = []
        skipped: list[str] = []
        while len(claimed) < max(batch_size, 0):
            popped = await client.zpopmin(queue_key, count=1)
            if not popped:
                break
            ticket_id = str(popped[0][0])
            ticket = await self.get_ticket(ticket_id)
            if ticket is None or not self._matches_labels(ticket, labels):
                skipped.append(ticket_id)
                continue
            updated = await self.update_status(ticket.ticket_id, TicketStatus.DISPATCHED)
            claimed.append(updated)
        await self._requeue_skipped(skipped)
        return claimed

    async def release_claim(self, ticket_id: str, reason: str) -> None:
        del reason
        await self.update_status(ticket_id, TicketStatus.QUEUED, assigned_to=None)

    async def save_result(self, result: TaskResult) -> None:
        client = self._client()
        await client.hset(self._result_key(result.ticket_id), mapping={"blob": encode_model(result)})
        ticket = await self.get_ticket(result.ticket_id)
        if ticket is None:
            return
        await self._write_ticket(ticket.model_copy(update={"result": result, "updated_at": result.completed_at}))

    async def get_result(self, ticket_id: str) -> TaskResult | None:
        client = self._client()
        raw = await client.hget(self._result_key(ticket_id), "blob")
        return decode_model(TaskResult, raw)

    async def query_tickets(
        self,
        *,
        status: TicketStatus | None = None,
        envelope_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[TaskTicket]:
        client = self._client()
        cursor = 0
        tickets: list[TaskTicket] = []
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=self._ticket_pattern(), count=100)
            for key in keys:
                ticket = await self.get_ticket(key.rsplit(":", 1)[-1])
                if ticket is None or not self._matches_ticket(ticket, status, envelope_id, labels):
                    continue
                tickets.append(ticket)
                if len(tickets) >= limit:
                    return tickets
            if cursor == 0:
                return tickets

    async def delete_ticket(self, ticket_id: str) -> None:
        client = self._client()
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            return
        await self._remove_ticket_indexes(ticket)
        await client.delete(self._ticket_key(ticket_id), self._result_key(ticket_id), self._running_key(ticket_id))

    async def aclose(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def _client(self):
        if self._redis is None:
            from redis import asyncio as redis_asyncio

            self._redis = redis_asyncio.Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def _write_ticket(self, ticket: TaskTicket) -> None:
        client = self._client()
        current = await self.get_ticket(ticket.ticket_id)
        if current is not None:
            await self._remove_ticket_indexes(current)
        mapping = {
            "blob": encode_model(ticket),
            "status": ticket.status.value,
            "envelope_id": ticket.envelope_id,
            "labels": json.dumps(ticket.labels, ensure_ascii=True, separators=(",", ":")),
        }
        await client.hset(self._ticket_key(ticket.ticket_id), mapping=mapping)
        await client.sadd(self._envelope_tickets_key(ticket.envelope_id), ticket.ticket_id)
        await self._enqueue_ticket(ticket)
        await self._apply_terminal_ttl(ticket)

    async def _enqueue_ticket(self, ticket: TaskTicket) -> None:
        client = self._client()
        if ticket.status != TicketStatus.QUEUED:
            return
        score = self._strategy.compute_score(ticket)
        await client.zadd(self._default_queue_key(), {ticket.ticket_id: score})
        for key, value in ticket.labels.items():
            await client.zadd(self._label_queue_key(key, value), {ticket.ticket_id: score})

    async def _remove_ticket_indexes(self, ticket: TaskTicket) -> None:
        client = self._client()
        await client.zrem(self._default_queue_key(), ticket.ticket_id)
        for key, value in ticket.labels.items():
            await client.zrem(self._label_queue_key(key, value), ticket.ticket_id)
        if ticket.status != TicketStatus.QUEUED:
            await client.delete(self._running_key(ticket.ticket_id))

    async def _sync_claim_lock(self, ticket: TaskTicket) -> None:
        client = self._client()
        if ticket.status in {TicketStatus.DISPATCHED, TicketStatus.RUNNING}:
            await client.set(
                self._running_key(ticket.ticket_id),
                ticket.status.value,
                ex=self._claim_ttl(ticket),
            )
            return
        await client.delete(self._running_key(ticket.ticket_id))

    async def _apply_terminal_ttl(self, ticket: TaskTicket) -> None:
        client = self._client()
        if not ticket.status.is_terminal:
            await client.persist(self._ticket_key(ticket.ticket_id))
            await client.persist(self._result_key(ticket.ticket_id))
            return
        await client.expire(self._ticket_key(ticket.ticket_id), self._terminal_ttl_seconds)
        await client.expire(self._result_key(ticket.ticket_id), self._terminal_ttl_seconds)

    async def _load_tickets(self, ticket_ids: list[str]) -> list[TaskTicket]:
        tickets: list[TaskTicket] = []
        for ticket_id in ticket_ids:
            ticket = await self.get_ticket(ticket_id)
            if ticket is not None:
                tickets.append(ticket)
        return tickets

    async def _requeue_skipped(self, ticket_ids: list[str]) -> None:
        for ticket_id in ticket_ids:
            ticket = await self.get_ticket(ticket_id)
            if ticket is not None and ticket.status == TicketStatus.QUEUED:
                await self._enqueue_ticket(ticket)

    def _matches_ticket(
        self,
        ticket: TaskTicket,
        status: TicketStatus | None,
        envelope_id: str | None,
        labels: dict[str, str] | None,
    ) -> bool:
        if status is not None and ticket.status != status:
            return False
        if envelope_id is not None and ticket.envelope_id != envelope_id:
            return False
        return self._matches_labels(ticket, labels)

    def _claim_ttl(self, ticket: TaskTicket) -> int:
        timeout_seconds = ticket.timeout_seconds or self._default_claim_ttl_seconds
        return max(timeout_seconds, 1)

    def _queue_key(self, labels: dict[str, str] | None) -> str:
        if not labels:
            return self._default_queue_key()
        key, value = next(iter(labels.items()))
        return self._label_queue_key(key, value)

    def _ticket_key(self, ticket_id: str) -> str:
        return f"{self._namespace}:ticket:{ticket_id}"

    def _ticket_pattern(self) -> str:
        return f"{self._namespace}:ticket:*"

    def _envelope_key(self, envelope_id: str) -> str:
        return f"{self._namespace}:envelope:{envelope_id}"

    def _envelope_tickets_key(self, envelope_id: str) -> str:
        return f"{self._namespace}:envelope:{envelope_id}:tids"

    def _default_queue_key(self) -> str:
        return f"{self._namespace}:queue:default"

    def _label_queue_key(self, key: str, value: str) -> str:
        return f"{self._namespace}:queue:label:{key}:{value}"

    def _running_key(self, ticket_id: str) -> str:
        return f"{self._namespace}:running:{ticket_id}"

    def _result_key(self, ticket_id: str) -> str:
        return f"{self._namespace}:result:{ticket_id}"

    @staticmethod
    def _matches_labels(ticket: TaskTicket, labels: dict[str, str] | None) -> bool:
        if labels is None:
            return True
        return all(ticket.labels.get(key) == value for key, value in labels.items())

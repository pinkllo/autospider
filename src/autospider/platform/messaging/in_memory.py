from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from autospider.platform.messaging.ports import Event
from autospider.platform.persistence.redis.keys import subtask_dead_queue_key, subtask_queue_key


@dataclass(slots=True)
class _StoredEvent:
    event: Event
    retry_count: int = 0


@dataclass(slots=True)
class _GroupState:
    offset: int = 0
    pending: dict[str, _StoredEvent] = field(default_factory=dict)


class InMemoryMessaging:
    def __init__(self, *, max_retries: int = 3) -> None:
        self._max_retries = max_retries
        self._streams: dict[str, list[_StoredEvent]] = {}
        self._groups: dict[tuple[str, str], _GroupState] = {}

    async def publish(self, stream: str, event: Event) -> str:
        entries = self._streams.setdefault(stream, [])
        event_id = f"{len(entries) + 1}-0"
        entries.append(_StoredEvent(event=event.model_copy(update={"id": event_id})))
        return event_id

    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        block_ms: int = 5000,
        batch: int = 16,
    ):
        state = self._groups.setdefault((stream, group), _GroupState())
        yielded = 0
        while state.offset < len(self._streams.get(stream, [])) and yielded < batch:
            stored = self._streams[stream][state.offset]
            state.pending[stored.event.id] = stored
            state.offset += 1
            yielded += 1
            yield stored.event
        if yielded == 0 and block_ms > 0:
            await asyncio.sleep(block_ms / 1000)

    async def ack(self, stream: str, group: str, event_id: str) -> None:
        state = self._groups.setdefault((stream, group), _GroupState())
        state.pending.pop(event_id, None)

    async def fail(self, stream: str, group: str, event_id: str, reason: str) -> None:
        state = self._groups.setdefault((stream, group), _GroupState())
        stored = state.pending.pop(event_id)
        payload = dict(stored.event.payload)
        payload["retry_count"] = stored.retry_count + 1
        payload["failure_reason"] = reason
        if stored.retry_count + 1 > self._max_retries and stream == subtask_queue_key():
            await self.publish(subtask_dead_queue_key(), stored.event.model_copy(update={"payload": payload}))
            return
        updated = stored.event.model_copy(update={"id": "", "payload": payload})
        self._streams.setdefault(stream, []).append(_StoredEvent(updated, stored.retry_count + 1))

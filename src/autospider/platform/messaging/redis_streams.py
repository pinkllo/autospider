from __future__ import annotations

import json

from redis import ResponseError

from autospider.platform.messaging.ports import Event
from autospider.platform.persistence.redis.keys import subtask_dead_queue_key, subtask_queue_key


class RedisStreamsMessaging:
    def __init__(self, client, *, max_retries: int = 3) -> None:
        self._client = client
        self._max_retries = max_retries

    async def publish(self, stream: str, event: Event) -> str:
        event_id = await self._client.xadd(stream, self._to_fields(event))
        return str(event_id)

    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        block_ms: int = 5000,
        batch: int = 16,
    ):
        await self._ensure_group(stream, group)
        response = await self._client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=batch,
            block=block_ms,
        )
        for _, messages in response:
            for event_id, fields in messages:
                yield self._from_fields(str(event_id), fields)

    async def ack(self, stream: str, group: str, event_id: str) -> None:
        await self._client.xack(stream, group, event_id)

    async def fail(self, stream: str, group: str, event_id: str, reason: str) -> None:
        stored = await self._load_event(stream, event_id)
        if stored is None:
            raise KeyError(event_id)
        payload = dict(stored.payload)
        retry_count = int(payload.get("retry_count", 0)) + 1
        payload["retry_count"] = retry_count
        payload["failure_reason"] = reason
        target_stream = stream
        if retry_count > self._max_retries and stream == subtask_queue_key():
            target_stream = subtask_dead_queue_key()
        await self._client.xack(stream, group, event_id)
        await self._client.xdel(stream, event_id)
        await self.publish(target_stream, stored.model_copy(update={"id": "", "payload": payload}))

    async def _ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._client.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _load_event(self, stream: str, event_id: str) -> Event | None:
        rows = await self._client.xrange(stream, min=event_id, max=event_id, count=1)
        if not rows:
            return None
        row_id, fields = rows[0]
        return self._from_fields(str(row_id), fields)

    def _to_fields(self, event: Event) -> dict[str, str]:
        return {
            "type": event.type,
            "run_id": event.run_id or "",
            "trace_id": event.trace_id,
            "occurred_at": event.occurred_at.isoformat(),
            "payload": json.dumps(event.payload, ensure_ascii=False),
        }

    def _from_fields(self, event_id: str, fields: dict[str, str]) -> Event:
        payload_text = str(fields.get("payload") or "{}")
        return Event(
            id=event_id,
            type=str(fields.get("type") or ""),
            run_id=str(fields.get("run_id") or "") or None,
            trace_id=str(fields.get("trace_id") or ""),
            occurred_at=str(fields.get("occurred_at") or ""),
            payload=json.loads(payload_text),
        )

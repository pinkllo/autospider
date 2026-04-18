from __future__ import annotations

from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from autospider.platform.messaging.ports import Event
from autospider.platform.messaging.redis_streams import RedisStreamsMessaging
from autospider.platform.persistence.redis.keys import subtask_dead_queue_key, subtask_queue_key


def _event() -> Event:
    return Event(
        type="planning.SubTaskPlanned",
        run_id="run-2",
        trace_id="trace-2",
        occurred_at=datetime.now(timezone.utc),
        payload={"subtask_id": "subtask-2"},
    )


async def _collect_first(async_iterable):
    async for item in async_iterable:
        return item
    raise AssertionError("expected at least one event")


@pytest.mark.asyncio
async def test_redis_streams_supports_retry_and_dead_letter() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    messaging = RedisStreamsMessaging(client, max_retries=1)
    stream = subtask_queue_key()
    await messaging.publish(stream, _event())

    first = await _collect_first(messaging.subscribe(stream, "workers", "consumer-1", block_ms=0))
    await messaging.fail(stream, "workers", first.id, "transient")

    retried = await _collect_first(messaging.subscribe(stream, "workers", "consumer-1", block_ms=0))
    assert retried.payload["retry_count"] == 1

    await messaging.fail(stream, "workers", retried.id, "fatal")
    dead_letter = await _collect_first(
        messaging.subscribe(subtask_dead_queue_key(), "dead-workers", "consumer-1", block_ms=0)
    )

    assert dead_letter.payload["failure_reason"] == "fatal"
    await client.aclose()


@pytest.mark.asyncio
async def test_redis_streams_ack_marks_event_complete() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    messaging = RedisStreamsMessaging(client)
    stream = subtask_queue_key()
    await messaging.publish(stream, _event())

    event = await _collect_first(messaging.subscribe(stream, "workers", "consumer-2", block_ms=0))
    await messaging.ack(stream, "workers", event.id)

    pending = await client.xpending(stream, "workers")
    assert int(pending["pending"]) == 0
    await client.aclose()

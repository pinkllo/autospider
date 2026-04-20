from __future__ import annotations

from datetime import datetime, timezone

import pytest

from autospider.platform.messaging.in_memory import InMemoryMessaging
from autospider.platform.messaging.ports import Event
from autospider.platform.persistence.redis.keys import subtask_dead_queue_key, subtask_queue_key


def _event() -> Event:
    return Event(
        type="planning.SubTaskPlanned",
        run_id="run-1",
        trace_id="trace-1",
        occurred_at=datetime.now(timezone.utc),
        payload={"subtask_id": "subtask-1"},
    )


async def _collect_first(async_iterable):
    async for item in async_iterable:
        return item
    raise AssertionError("expected at least one event")


@pytest.mark.asyncio
async def test_in_memory_messaging_supports_retry_and_dead_letter() -> None:
    messaging = InMemoryMessaging(max_retries=1)
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


@pytest.mark.asyncio
async def test_in_memory_messaging_ack_clears_pending_event() -> None:
    messaging = InMemoryMessaging()
    stream = subtask_queue_key()
    await messaging.publish(stream, _event())

    event = await _collect_first(messaging.subscribe(stream, "workers", "consumer-2", block_ms=0))
    await messaging.ack(stream, "workers", event.id)

    remaining = [
        item async for item in messaging.subscribe(stream, "workers", "consumer-2", block_ms=0)
    ]
    assert remaining == []

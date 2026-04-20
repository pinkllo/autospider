from __future__ import annotations

import pytest

from autospider.contexts.collection.infrastructure.channel.redis_channel import RedisURLChannel


class _FakeRedisManager:
    def __init__(self) -> None:
        self.release_calls: list[tuple[str, str, str]] = []
        self.stream_length = 0

    async def connect(self) -> object:
        return object()

    async def recover_stale_tasks(
        self,
        *,
        consumer_name: str,
        max_idle_ms: int,
        count: int,
    ) -> list[tuple[str, str, dict]]:
        return []

    async def fetch_task(
        self,
        *,
        consumer_name: str,
        block_ms: int,
        count: int,
    ) -> list[tuple[str, str, dict]]:
        return [("stream-1", "data-1", {"url": "https://example.com/item-1"})]

    async def release_task(self, stream_id: str, data_id: str, reason: str) -> bool:
        self.release_calls.append((stream_id, data_id, reason))
        return True

    async def get_pending_count(self, consumer_name: str | None = None) -> int:
        return 0

    async def get_stream_length(self) -> int:
        return self.stream_length

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redis_channel_release_task_requeues_message_without_counting_failure() -> None:
    manager = _FakeRedisManager()
    channel = RedisURLChannel(manager=manager, consumer_name="consumer-1")

    tasks = await channel.fetch(max_items=1, timeout_s=0)
    await tasks[0].release_task("browser_intervention")

    assert manager.release_calls == [("stream-1", "data-1", "browser_intervention")]


@pytest.mark.asyncio
async def test_is_drained_checks_global_stream_length() -> None:
    manager = _FakeRedisManager()
    manager.stream_length = 1
    channel = RedisURLChannel(manager=manager, consumer_name="consumer-1")

    await channel.seal()

    assert await channel.is_drained() is False

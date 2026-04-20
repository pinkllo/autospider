from __future__ import annotations

import pytest

from autospider.legacy.common.channel.base import ChannelRuntimeEvent
from autospider.legacy.common.channel.redis_channel import RedisURLChannel
from autospider.legacy.common.config import config


class _FakeRedisManager:
    def __init__(self) -> None:
        self.fetch_tasks = [("stream-1", "data-1", {"url": "https://example.com/item-1"})]
        self.recovered_tasks: list[tuple[str, str, dict]] = []
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
        return list(self.recovered_tasks)

    async def fetch_task(
        self,
        *,
        consumer_name: str,
        block_ms: int,
        count: int,
    ) -> list[tuple[str, str, dict]]:
        return list(self.fetch_tasks[:count])

    async def release_task(self, stream_id: str, data_id: str, reason: str) -> bool:
        self.release_calls.append((stream_id, data_id, reason))
        return True

    async def get_stream_length(self) -> int:
        return self.stream_length

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_fetch_and_release_emit_runtime_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[ChannelRuntimeEvent] = []
    manager = _FakeRedisManager()
    monkeypatch.setattr(config.redis, "auto_recover", False, raising=False)
    channel = RedisURLChannel(
        manager=manager,
        consumer_name="consumer-1",
        runtime_observer=events.append,
    )

    tasks = await channel.fetch(max_items=1, timeout_s=0)
    await tasks[0].release_task("browser_intervention")

    assert [event.operation for event in events] == ["fetch", "release"]
    assert events[0].item_count == 1
    assert events[0].metadata["source"] == "redis"
    assert events[0].metadata["block_ms"] == 0
    assert events[1].item_count == 1
    assert events[1].reason == "browser_intervention"
    assert events[1].metadata["data_id"] == "data-1"


@pytest.mark.asyncio
async def test_recover_and_is_drained_emit_runtime_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[ChannelRuntimeEvent] = []
    manager = _FakeRedisManager()
    manager.fetch_tasks = []
    manager.recovered_tasks = [("stream-2", "data-2", {"url": "https://example.com/item-2"})]
    channel = RedisURLChannel(
        manager=manager,
        consumer_name="consumer-1",
        runtime_observer=events.append,
    )
    channel._connected = True
    monkeypatch.setattr(config.redis, "auto_recover", True, raising=False)
    monkeypatch.setattr(config.redis, "task_timeout_ms", 1000, raising=False)
    monkeypatch.setattr(config.redis, "fetch_batch_size", 5, raising=False)

    await channel._recover_pending_once()
    await channel.seal()
    manager.stream_length = 1
    assert await channel.is_drained() is False
    channel._retry_buffer.clear()
    manager.stream_length = 0
    assert await channel.is_drained() is True

    assert [event.operation for event in events] == ["recover", "is_drained", "is_drained"]
    assert events[0].item_count == 1
    assert events[0].metadata["retry_buffer_size"] == 1
    assert events[1].drained is False
    assert events[1].metadata["stream_length"] == 1
    assert events[2].drained is True
    assert events[2].metadata["stream_length"] == 0

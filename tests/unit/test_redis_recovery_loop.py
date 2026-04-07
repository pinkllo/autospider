from __future__ import annotations

import asyncio

import pytest

from autospider.common.channel.redis_channel import RedisURLChannel
from autospider.common.channel import redis_channel as redis_channel_module
from autospider.common.storage.redis_manager import RedisQueueManager


class _FakeManager:
    def __init__(self) -> None:
        self.connect_calls = 0
        self.fetch_calls: list[dict[str, object]] = []
        self.recover_calls: list[dict[str, object]] = []
        self.fail_calls: list[dict[str, object]] = []
        self.acked: list[tuple[str, str | None]] = []
        self._fresh_tasks: list[list[tuple[str, str, dict]]] = []
        self._recovered_tasks: list[list[tuple[str, str, dict]]] = []
        self.fail_result = "retry"

    async def connect(self):
        self.connect_calls += 1
        return object()

    async def push_task(self, url: str) -> None:
        return None

    async def fetch_task(self, *, consumer_name: str, block_ms: int, count: int):
        self.fetch_calls.append(
            {"consumer_name": consumer_name, "block_ms": block_ms, "count": count}
        )
        if self._fresh_tasks:
            return self._fresh_tasks.pop(0)
        return []

    async def recover_stale_tasks(self, *, consumer_name: str, max_idle_ms: int, count: int):
        self.recover_calls.append(
            {"consumer_name": consumer_name, "max_idle_ms": max_idle_ms, "count": count}
        )
        if self._recovered_tasks:
            return self._recovered_tasks.pop(0)
        return []

    async def ack_task(self, stream_id: str, data_id: str | None = None) -> bool:
        self.acked.append((stream_id, data_id))
        return True

    async def fail_task_state(self, stream_id: str, data_id: str, error_msg: str | None = None, max_retries: int = 3) -> str:
        self.fail_calls.append(
            {
                "stream_id": stream_id,
                "data_id": data_id,
                "error_msg": error_msg,
                "max_retries": max_retries,
            }
        )
        return self.fail_result

    async def close(self) -> None:
        return None


class _UnavailableManager(_FakeManager):
    async def connect(self):
        self.connect_calls += 1
        return None


class _ExplodingRecoverManager(_FakeManager):
    async def recover_stale_tasks(self, *, consumer_name: str, max_idle_ms: int, count: int):
        self.recover_calls.append(
            {"consumer_name": consumer_name, "max_idle_ms": max_idle_ms, "count": count}
        )
        raise RuntimeError("redis down")


@pytest.mark.asyncio
async def test_fetch_raises_when_redis_connection_unavailable():
    manager = _UnavailableManager()
    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    with pytest.raises(RuntimeError, match="redis_channel_unavailable"):
        await channel.fetch(max_items=1, timeout_s=0)


@pytest.mark.asyncio
async def test_publish_raises_when_redis_connection_unavailable():
    manager = _UnavailableManager()
    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    with pytest.raises(RuntimeError, match="redis_channel_unavailable"):
        await channel.publish("https://example.com/a")


@pytest.mark.asyncio
async def test_initial_recovery_failure_is_not_masked(monkeypatch):
    manager = _ExplodingRecoverManager()

    monkeypatch.setattr(redis_channel_module.config.redis, "auto_recover", True, raising=False)
    monkeypatch.setattr(redis_channel_module.config.redis, "task_timeout_ms", 1000, raising=False)
    monkeypatch.setattr(redis_channel_module.config.redis, "fetch_batch_size", 10, raising=False)

    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    with pytest.raises(RuntimeError, match="redis down"):
        await channel.fetch(max_items=1, timeout_s=0)


@pytest.mark.asyncio
async def test_background_recovery_failure_poison_pills_follow_up_fetch(monkeypatch):
    manager = _FakeManager()
    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    errors: list[str] = []

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(channel, "_recover_pending_once", _boom)
    monkeypatch.setattr(redis_channel_module.config.redis, "auto_recover", True, raising=False)
    monkeypatch.setattr(redis_channel_module.config.redis, "task_timeout_ms", 1, raising=False)
    monkeypatch.setattr(redis_channel_module.logger, "error", lambda msg, *args: errors.append(msg % args))

    channel._start_recover_loop()
    await asyncio.sleep(1.1)

    with pytest.raises(RuntimeError, match="redis_recovery_failed: redis down"):
        await channel.fetch(max_items=1, timeout_s=0)

    await channel.close()
    assert any("后台恢复失败" in message for message in errors)


@pytest.mark.asyncio
async def test_recovered_tasks_are_buffered_and_delivered_before_fresh_messages(monkeypatch):
    manager = _FakeManager()
    manager._fresh_tasks.append([("2-0", "fresh", {"url": "https://example.com/fresh"})])
    manager._recovered_tasks.append([("1-0", "stale", {"url": "https://example.com/stale"})])

    monkeypatch.setattr(redis_channel_module.config.redis, "auto_recover", True, raising=False)
    monkeypatch.setattr(redis_channel_module.config.redis, "task_timeout_ms", 1000, raising=False)
    monkeypatch.setattr(redis_channel_module.config.redis, "fetch_batch_size", 10, raising=False)

    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    recovered_first = await channel.fetch(max_items=1, timeout_s=0)
    fresh_second = await channel.fetch(max_items=1, timeout_s=0)

    assert [task.url for task in recovered_first] == ["https://example.com/stale"]
    assert [task.url for task in fresh_second] == ["https://example.com/fresh"]
    assert len(manager.fetch_calls) == 1


@pytest.mark.asyncio
async def test_retryable_failure_reenters_local_buffer_without_refetching_pending():
    manager = _FakeManager()
    manager._fresh_tasks.append([("1-0", "retryable", {"url": "https://example.com/retry"})])
    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    first = await channel.fetch(max_items=1, timeout_s=0)
    assert [task.url for task in first] == ["https://example.com/retry"]

    await first[0].fail_task("boom")
    second = await channel.fetch(max_items=1, timeout_s=0)

    assert [task.url for task in second] == ["https://example.com/retry"]
    assert len(manager.fetch_calls) == 1
    assert manager.fail_calls[0]["error_msg"] == "boom"


@pytest.mark.asyncio
async def test_non_retryable_failure_is_not_rebuffered():
    manager = _FakeManager()
    manager.fail_result = "dead_letter"
    manager._fresh_tasks.append([("1-0", "dead", {"url": "https://example.com/dead"})])
    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    first = await channel.fetch(max_items=1, timeout_s=0)
    await first[0].fail_task("boom")
    second = await channel.fetch(max_items=1, timeout_s=0)

    assert [task.url for task in first] == ["https://example.com/dead"]
    assert second == []


@pytest.mark.asyncio
async def test_ack_callback_passes_data_id_for_cleanup():
    manager = _FakeManager()
    manager._fresh_tasks.append([("1-0", "item-1", {"url": "https://example.com/ok"})])
    channel = RedisURLChannel(manager=manager, consumer_name="worker-a", block_ms=0, max_retries=3)

    tasks = await channel.fetch(max_items=1, timeout_s=0)
    await tasks[0].ack_task()

    assert manager.acked == [("1-0", "item-1")]


@pytest.mark.asyncio
async def test_fail_task_state_preserves_boolean_fail_task_contract(monkeypatch):
    manager = RedisQueueManager(key_prefix="test:boolean-contract")

    async def _fake_state(*args, **kwargs):
        return "retry"

    monkeypatch.setattr(manager, "fail_task_state", _fake_state)

    assert await manager.fail_task("1-0", "item-1", "boom", max_retries=3) is True

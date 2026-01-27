"""Redis-backed URL channel."""

from __future__ import annotations

import asyncio
import socket
import os
from typing import Callable

from .base import URLChannel, URLTask
from ..storage.redis_manager import RedisQueueManager
from ..config import config


class RedisURLChannel(URLChannel):
    """Redis Stream URL channel wrapper."""

    def __init__(
        self,
        manager: RedisQueueManager,
        consumer_name: str | None = None,
        block_ms: int = 5000,
        max_retries: int = 3,
    ) -> None:
        self.manager = manager
        self.consumer_name = (
            consumer_name
            or f"pipeline-{socket.gethostname()}-{os.getpid()}"
        )
        self.block_ms = block_ms
        self.max_retries = max_retries
        self._connected = False
        self._recover_task: asyncio.Task | None = None

    async def _recover_pending_once(self) -> None:
        if not self._connected or not config.redis.auto_recover:
            return
        await self.manager.recover_stale_tasks(
            consumer_name=self.consumer_name,
            max_idle_ms=config.redis.task_timeout_ms,
            count=config.redis.fetch_batch_size,
        )

    def _start_recover_loop(self) -> None:
        if self._recover_task is not None or not config.redis.auto_recover:
            return

        interval_s = max(1, int(config.redis.task_timeout_ms / 1000))

        async def _loop() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_s)
                    await self._recover_pending_once()
                except asyncio.CancelledError:
                    break
                except Exception:
                    continue

        self._recover_task = asyncio.create_task(_loop())

    async def _ensure_connected(self) -> None:
        if self._connected:
            return
        client = await self.manager.connect()
        self._connected = client is not None
        if self._connected and config.redis.auto_recover:
            await self._recover_pending_once()
            self._start_recover_loop()

    async def publish(self, url: str) -> None:
        await self._ensure_connected()
        if not self._connected:
            return
        await self.manager.push_task(url)

    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        await self._ensure_connected()
        if not self._connected:
            return []

        block_ms = self.block_ms
        if timeout_s is not None:
            if timeout_s <= 0:
                block_ms = 0
            else:
                block_ms = int(timeout_s * 1000)

        tasks = await self.manager.fetch_task(
            consumer_name=self.consumer_name,
            block_ms=block_ms,
            count=max_items,
        )

        wrapped: list[URLTask] = []
        for stream_id, data_id, data in tasks:
            url = data.get("url", "")

            async def _ack(sid: str = stream_id) -> None:
                await self.manager.ack_task(sid)

            async def _fail(
                reason: str,
                sid: str = stream_id,
                did: str = data_id,
            ) -> None:
                await self.manager.fail_task(
                    sid,
                    did,
                    reason,
                    max_retries=self.max_retries,
                )

            wrapped.append(URLTask(url=url, ack=_ack, fail=_fail))

        return wrapped

    async def close(self) -> None:
        if self._recover_task is not None:
            self._recover_task.cancel()
            self._recover_task = None

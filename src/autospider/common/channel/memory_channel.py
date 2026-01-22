"""In-memory URL channel based on asyncio.Queue."""

from __future__ import annotations

import asyncio
from typing import Any

from .base import URLChannel, URLTask


class MemoryURLChannel(URLChannel):
    """In-memory URL channel for single-process pipelines."""

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def publish(self, url: str) -> None:
        if self._closed:
            return
        await self._queue.put(url)

    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        if self._closed and self._queue.empty():
            return []

        items: list[URLTask] = []

        try:
            if timeout_s is None:
                first = await self._queue.get()
            elif timeout_s <= 0:
                return []
            else:
                first = await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return []

        if first is None:
            self._closed = True
            return []

        items.append(URLTask(url=str(first)))

        while len(items) < max_items:
            try:
                next_item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if next_item is None:
                self._closed = True
                break
            items.append(URLTask(url=str(next_item)))

        return items

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)

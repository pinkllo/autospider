"""URL channel abstractions and task wrapper."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Awaitable, Callable


AckFn = Callable[[], Awaitable[None]]
FailFn = Callable[[str], Awaitable[None]]


@dataclass
class URLTask:
    """URL task wrapper with optional ack/fail callbacks."""

    url: str
    ack: AckFn | None = None
    fail: FailFn | None = None

    async def ack_task(self) -> None:
        if self.ack:
            await self.ack()

    async def fail_task(self, reason: str) -> None:
        if self.fail:
            await self.fail(reason)


class URLChannel(abc.ABC):
    """Abstract URL channel."""

    @abc.abstractmethod
    async def publish(self, url: str) -> None:
        """Publish a single URL."""

    async def publish_many(self, urls: list[str]) -> None:
        """Publish multiple URLs (default: sequential)."""
        for url in urls:
            await self.publish(url)

    @abc.abstractmethod
    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        """Fetch URL tasks."""

    async def close(self) -> None:
        """Close channel (default: no-op)."""
        return None

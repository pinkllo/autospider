"""URL channel abstractions and task wrapper."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


AckFn = Callable[[], Awaitable[None]]
FailFn = Callable[[str], Awaitable[None]]
ReleaseFn = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ChannelRuntimeEvent:
    operation: str
    item_count: int = 0
    reason: str = ""
    drained: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


ChannelRuntimeObserver = Callable[[ChannelRuntimeEvent], None]


@dataclass
class URLTask:
    """URL task wrapper with optional ack/fail callbacks."""

    url: str
    ack: AckFn | None = None
    fail: FailFn | None = None
    release: ReleaseFn | None = None

    async def ack_task(self) -> None:
        if self.ack:
            await self.ack()

    async def fail_task(self, reason: str) -> None:
        if self.fail:
            await self.fail(reason)

    async def release_task(self, reason: str) -> None:
        if self.release is None:
            raise RuntimeError("task_release_unsupported")
        await self.release(reason)


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

    async def list_existing_urls(self) -> list[str]:
        """List already persisted URLs for resume/recovery flows."""
        return []

    def persists_published_urls(self) -> bool:
        """Return whether publish() already durably maintains a URL listing."""
        return False

    async def seal(self) -> None:
        """Signal that no more items will be published."""
        return None

    async def is_drained(self) -> bool:
        """Return whether the channel has been sealed and fully drained."""
        return False

    async def close_with_error(self, reason: str) -> None:
        """Close channel with an explicit terminal error."""
        await self.close()

    async def close(self) -> None:
        """Close channel (default: no-op)."""
        return None


UrlQueueBackend = URLChannel

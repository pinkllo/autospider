from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class Event(BaseModel):
    id: str = ""
    type: str
    run_id: str | None = None
    trace_id: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class Messaging(Protocol):
    async def publish(self, stream: str, event: Event) -> str:
        ...

    async def subscribe(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        block_ms: int = 5000,
        batch: int = 16,
    ) -> AsyncIterator[Event]:
        ...

    async def ack(self, stream: str, group: str, event_id: str) -> None:
        ...

    async def fail(self, stream: str, group: str, event_id: str, reason: str) -> None:
        ...

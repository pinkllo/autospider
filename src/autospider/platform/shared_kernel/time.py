from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, TypeAlias

UtcDatetime: TypeAlias = datetime


class Clock(Protocol):
    def now(self) -> UtcDatetime:
        ...


class SystemClock:
    def now(self) -> UtcDatetime:
        return datetime.now(timezone.utc)

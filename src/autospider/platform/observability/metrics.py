from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator


@dataclass(slots=True)
class MetricsRegistry:
    counters: dict[str, int] = field(default_factory=dict)
    timings_ms: dict[str, list[float]] = field(default_factory=dict)

    def increment(self, name: str, value: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + value

    def record_timing(self, name: str, duration_ms: float) -> None:
        values = self.timings_ms.setdefault(name, [])
        values.append(round(duration_ms, 4))

    @contextmanager
    def time(self, name: str) -> Iterator[None]:
        started_at = perf_counter()
        try:
            yield
        finally:
            self.record_timing(name, (perf_counter() - started_at) * 1000)

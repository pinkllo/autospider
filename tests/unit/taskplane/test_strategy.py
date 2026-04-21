from datetime import datetime, timedelta, timezone

import pytest

from autospider.composition.taskplane.protocol import TaskTicket
from autospider.composition.taskplane.strategy import (
    BatchAwareStrategy,
    FIFOStrategy,
    PriorityStrategy,
)


def _ticket(
    ticket_id: str,
    envelope_id: str = "e1",
    priority: int = 0,
    offset_seconds: int = 0,
) -> TaskTicket:
    return TaskTicket(
        ticket_id=ticket_id,
        envelope_id=envelope_id,
        priority=priority,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds),
    )


class TestFIFOStrategy:
    def test_earlier_ticket_has_lower_score(self):
        strategy = FIFOStrategy()
        early = _ticket("a", offset_seconds=0)
        late = _ticket("b", offset_seconds=10)
        assert strategy.compute_score(early) < strategy.compute_score(late)


class TestPriorityStrategy:
    def test_lower_priority_value_has_lower_score(self):
        strategy = PriorityStrategy()
        high = _ticket("a", priority=0)
        low = _ticket("b", priority=5)
        assert strategy.compute_score(high) < strategy.compute_score(low)

    def test_same_priority_ordered_by_time(self):
        strategy = PriorityStrategy()
        first = _ticket("a", priority=1, offset_seconds=0)
        second = _ticket("b", priority=1, offset_seconds=10)
        assert strategy.compute_score(first) < strategy.compute_score(second)


class TestBatchAwareStrategy:
    def test_same_envelope_is_clustered_ahead_of_time_only_ordering(self):
        strategy = BatchAwareStrategy()
        first = _ticket("a", envelope_id="e1", priority=0, offset_seconds=0)
        second = _ticket("b", envelope_id="e1", priority=0, offset_seconds=1)
        other = _ticket("c", envelope_id="e2", priority=0, offset_seconds=0)

        same_gap = abs(strategy.compute_score(first) - strategy.compute_score(second))
        cross_gap = abs(strategy.compute_score(first) - strategy.compute_score(other))

        assert same_gap == pytest.approx(1.0)
        assert cross_gap > same_gap


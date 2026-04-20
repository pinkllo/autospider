"""Dispatch strategies that control ticket ordering in the queue."""

from __future__ import annotations

from hashlib import sha1
from typing import Protocol, runtime_checkable

from .protocol import TaskTicket

_PRIORITY_WEIGHT = 1_000_000_000_000_000.0
_ENVELOPE_WEIGHT = 1_000_000.0


def _stable_envelope_cluster(envelope_id: str) -> int:
    digest = sha1(envelope_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


@runtime_checkable
class DispatchStrategy(Protocol):
    def compute_score(self, ticket: TaskTicket) -> float:
        """Return a numeric score where lower values are dispatched first."""


class FIFOStrategy:
    """First-in-first-out: ordered by creation time."""

    def compute_score(self, ticket: TaskTicket) -> float:
        return ticket.created_at.timestamp()


class PriorityStrategy:
    """Priority-first: lower priority value = higher urgency. Ties break by time."""

    def compute_score(self, ticket: TaskTicket) -> float:
        return ticket.priority * _PRIORITY_WEIGHT + ticket.created_at.timestamp()


class BatchAwareStrategy:
    """Batch-aware: tickets from the same envelope cluster together."""

    def compute_score(self, ticket: TaskTicket) -> float:
        cluster = _stable_envelope_cluster(ticket.envelope_id)
        return (
            ticket.priority * _PRIORITY_WEIGHT
            + cluster * _ENVELOPE_WEIGHT
            + ticket.created_at.timestamp()
        )

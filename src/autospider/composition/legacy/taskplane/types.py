"""Auxiliary types: receipts, progress, configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .protocol import TicketStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SubmitReceipt:
    envelope_id: str
    ticket_count: int
    queued_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class ReportReceipt:
    ticket_id: str
    final_status: TicketStatus
    retried: bool
    spawned_count: int


@dataclass(frozen=True, slots=True)
class EnvelopeProgress:
    envelope_id: str
    total: int = 0
    queued: int = 0
    dispatched: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    expanded: int = 0
    cancelled: int = 0


@dataclass(slots=True)
class TaskPlaneConfig:
    redis_url: str = ""
    pg_url: str = ""
    fallback_to_memory: bool = True
    default_strategy: str = "priority"
    default_max_attempts: int = 3
    default_timeout_seconds: int = 600
    redis_hot_ttl_seconds: int = 3600
    reaper_interval_seconds: int = 30
    max_subscription_concurrency: int = 32

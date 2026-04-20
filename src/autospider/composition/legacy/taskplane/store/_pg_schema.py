from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")
metadata = MetaData()

plan_envelopes = Table(
    "plan_envelopes",
    metadata,
    Column("envelope_id", String(64), primary_key=True),
    Column("source_agent", String(128), default=""),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("metadata", JSON_VALUE, default=dict, nullable=False),
    Column("plan_snapshot", JSON_VALUE, default=dict, nullable=False),
    Column("archived_at", DateTime(timezone=True), nullable=True),
)

task_tickets = Table(
    "task_tickets",
    metadata,
    Column("ticket_id", String(64), primary_key=True),
    Column("envelope_id", String(64), ForeignKey("plan_envelopes.envelope_id"), nullable=False),
    Column("parent_ticket_id", String(64), nullable=True),
    Column("status", String(32), nullable=False, default="registered"),
    Column("priority", Integer, default=0, nullable=False),
    Column("payload", JSON_VALUE, default=dict, nullable=False),
    Column("labels", JSON_VALUE, default=dict, nullable=False),
    Column("assigned_to", String(128), nullable=True),
    Column("attempt_count", Integer, default=0, nullable=False),
    Column("max_attempts", Integer, default=3, nullable=False),
    Column("timeout_seconds", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

task_results = Table(
    "task_results",
    metadata,
    Column("result_id", String(64), primary_key=True),
    Column("ticket_id", String(64), ForeignKey("task_tickets.ticket_id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("output", JSON_VALUE, default=dict, nullable=False),
    Column("error", Text, default="", nullable=False),
    Column("artifacts", JSON_VALUE, default=list, nullable=False),
    Column("spawned_tickets", JSON_VALUE, default=list, nullable=False),
    Column("completed_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

Index("idx_tickets_status", task_tickets.c.status)
Index("idx_tickets_envelope", task_tickets.c.envelope_id)
Index("idx_tickets_labels", task_tickets.c.labels, postgresql_using="gin")
Index("idx_tickets_priority", task_tickets.c.priority, task_tickets.c.created_at)


def normalize_database_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"postgresql", "postgresql+psycopg2"}:
        return url
    return urlunsplit(
        ("postgresql+psycopg", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )

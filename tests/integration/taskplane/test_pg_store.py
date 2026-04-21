from __future__ import annotations

import pytest

from autospider.composition.taskplane.protocol import (
    PlanEnvelope,
    ResultStatus,
    TaskResult,
    TaskTicket,
    TicketStatus,
)

pytestmark = pytest.mark.integration


def _envelope() -> PlanEnvelope:
    return PlanEnvelope(
        envelope_id="env-pg",
        source_agent="integration",
        metadata={"topic": "pg"},
        plan_snapshot={"step": "store"},
    )


def _ticket(ticket_id: str, *, priority: int = 0, mode: str = "collect") -> TaskTicket:
    return TaskTicket(
        ticket_id=ticket_id,
        envelope_id="env-pg",
        status=TicketStatus.QUEUED,
        priority=priority,
        labels={"mode": mode},
        payload={"url": f"https://example.com/{ticket_id}"},
    )


def test_pg_store_module_exists() -> None:
    from autospider.composition.taskplane.store.pg_store import PgColdStore

    assert PgColdStore is not None


async def test_save_and_query_tickets(
    taskplane_database_url: str,
    pg_isolated_tables: None,
) -> None:
    from autospider.composition.taskplane.store.pg_store import PgColdStore

    store = PgColdStore(database_url=taskplane_database_url)
    await store.save_envelope(_envelope())
    await store.save_tickets_batch(
        [
            _ticket("ticket-a", priority=2),
            _ticket("ticket-b", priority=0, mode="expand"),
        ]
    )

    try:
        envelope = await store.get_envelope("env-pg")
        queued = await store.query_tickets(status=TicketStatus.QUEUED, labels={"mode": "collect"})
        by_envelope = await store.get_tickets_by_envelope("env-pg")

        assert envelope is not None
        assert envelope.metadata["topic"] == "pg"
        assert [ticket.ticket_id for ticket in queued] == ["ticket-a"]
        assert {ticket.ticket_id for ticket in by_envelope} == {"ticket-a", "ticket-b"}
    finally:
        await store.aclose()


async def test_claim_and_release_roundtrip(
    taskplane_database_url: str,
    pg_isolated_tables: None,
) -> None:
    from autospider.composition.taskplane.store.pg_store import PgColdStore

    store = PgColdStore(database_url=taskplane_database_url)
    await store.save_ticket(_ticket("ticket-claim", priority=1))

    claimed = await store.claim_next(batch_size=1)
    assert [ticket.ticket_id for ticket in claimed] == ["ticket-claim"]

    await store.release_claim("ticket-claim", reason="retry")
    restored = await store.get_ticket("ticket-claim")

    try:
        assert restored is not None
        assert restored.status == TicketStatus.QUEUED
    finally:
        await store.aclose()


async def test_save_result_roundtrip(
    taskplane_database_url: str,
    pg_isolated_tables: None,
) -> None:
    from autospider.composition.taskplane.store.pg_store import PgColdStore

    store = PgColdStore(database_url=taskplane_database_url)
    await store.save_envelope(_envelope())
    await store.save_ticket(_ticket("ticket-result"))
    await store.update_status("ticket-result", TicketStatus.RUNNING, assigned_to="worker-pg")

    result = TaskResult(
        result_id="result-pg",
        ticket_id="ticket-result",
        status=ResultStatus.SUCCESS,
        output={"items": 5},
    )
    await store.save_result(result)
    await store.update_status("ticket-result", TicketStatus.COMPLETED, assigned_to="worker-pg")

    stored_result = await store.get_result("ticket-result")
    stored_ticket = await store.get_ticket("ticket-result")

    try:
        assert stored_result is not None
        assert stored_result.result_id == "result-pg"
        assert stored_ticket is not None
        assert stored_ticket.status == TicketStatus.COMPLETED
        assert stored_ticket.result is not None
    finally:
        await store.aclose()


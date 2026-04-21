from __future__ import annotations

import pytest

from autospider.composition.taskplane.protocol import (
    PlanEnvelope,
    ResultStatus,
    TaskResult,
    TaskTicket,
    TicketStatus,
)
from autospider.composition.taskplane.strategy import PriorityStrategy

pytestmark = pytest.mark.integration


def _envelope() -> PlanEnvelope:
    return PlanEnvelope(envelope_id="env-redis", source_agent="integration")


def _ticket(ticket_id: str, *, priority: int = 0, mode: str = "collect") -> TaskTicket:
    return TaskTicket(
        ticket_id=ticket_id,
        envelope_id="env-redis",
        status=TicketStatus.QUEUED,
        priority=priority,
        labels={"mode": mode},
        timeout_seconds=30,
    )


def test_redis_store_module_exists() -> None:
    from autospider.composition.taskplane.store.redis_store import RedisHotStore

    assert RedisHotStore is not None


async def test_save_and_claim_tickets_by_priority_and_label(
    taskplane_redis_url: str,
    redis_namespace: str,
) -> None:
    from autospider.composition.taskplane.store.redis_store import RedisHotStore

    store = RedisHotStore(
        redis_url=taskplane_redis_url,
        namespace=redis_namespace,
        strategy=PriorityStrategy(),
    )
    await store.save_envelope(_envelope())
    await store.save_tickets_batch(
        [
            _ticket("ticket-low", priority=5),
            _ticket("ticket-high", priority=0),
            _ticket("ticket-expand", priority=1, mode="expand"),
        ]
    )

    claimed = await store.claim_next(labels={"mode": "collect"}, batch_size=2)

    try:
        assert [ticket.ticket_id for ticket in claimed] == ["ticket-high", "ticket-low"]
        persisted = await store.get_ticket("ticket-high")
        assert persisted is not None
        assert persisted.status == TicketStatus.DISPATCHED
    finally:
        await store.aclose()


async def test_release_claim_requeues_ticket(
    taskplane_redis_url: str,
    redis_namespace: str,
) -> None:
    from autospider.composition.taskplane.store.redis_store import RedisHotStore

    store = RedisHotStore(redis_url=taskplane_redis_url, namespace=redis_namespace)
    await store.save_ticket(_ticket("ticket-release"))
    claimed = await store.claim_next(batch_size=1)
    assert [ticket.ticket_id for ticket in claimed] == ["ticket-release"]

    await store.release_claim("ticket-release", reason="worker_restart")
    restored = await store.get_ticket("ticket-release")

    try:
        assert restored is not None
        assert restored.status == TicketStatus.QUEUED
        assert restored.assigned_to is None
    finally:
        await store.aclose()


async def test_save_result_persists_result_and_terminal_status(
    taskplane_redis_url: str,
    redis_namespace: str,
) -> None:
    from autospider.composition.taskplane.store.redis_store import RedisHotStore

    store = RedisHotStore(redis_url=taskplane_redis_url, namespace=redis_namespace)
    await store.save_ticket(_ticket("ticket-result"))
    await store.update_status("ticket-result", TicketStatus.RUNNING, assigned_to="worker-1")

    result = TaskResult(
        result_id="result-redis",
        ticket_id="ticket-result",
        status=ResultStatus.SUCCESS,
        output={"items": 3},
    )
    await store.save_result(result)
    await store.update_status("ticket-result", TicketStatus.COMPLETED, assigned_to="worker-1")

    stored_result = await store.get_result("ticket-result")
    stored_ticket = await store.get_ticket("ticket-result")

    try:
        assert stored_result is not None
        assert stored_result.output == {"items": 3}
        assert stored_ticket is not None
        assert stored_ticket.status == TicketStatus.COMPLETED
        assert stored_ticket.result is not None
    finally:
        await store.aclose()


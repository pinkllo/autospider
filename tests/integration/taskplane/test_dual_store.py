from __future__ import annotations

import asyncio

import pytest

from autospider.legacy.taskplane.protocol import (
    PlanEnvelope,
    ResultStatus,
    TaskResult,
    TaskTicket,
    TicketStatus,
)

pytestmark = pytest.mark.integration


def _envelope() -> PlanEnvelope:
    return PlanEnvelope(envelope_id="env-dual", source_agent="integration")


def _ticket(ticket_id: str, *, priority: int = 0) -> TaskTicket:
    return TaskTicket(
        ticket_id=ticket_id,
        envelope_id="env-dual",
        status=TicketStatus.QUEUED,
        priority=priority,
        labels={"mode": "collect"},
    )


def test_dual_store_module_exists() -> None:
    from autospider.legacy.taskplane.store.dual_store import DualLayerStore

    assert DualLayerStore is not None


async def _wait_until(predicate, *, timeout_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        if await predicate():
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition_not_met_within_timeout")
        await asyncio.sleep(0.05)


async def test_hot_write_reaches_cold_store_asynchronously(
    taskplane_redis_url: str,
    taskplane_database_url: str,
    redis_namespace: str,
    pg_isolated_tables: None,
) -> None:
    from autospider.legacy.taskplane.store.dual_store import DualLayerStore
    from autospider.legacy.taskplane.store.pg_store import PgColdStore
    from autospider.legacy.taskplane.store.redis_store import RedisHotStore

    hot_store = RedisHotStore(redis_url=taskplane_redis_url, namespace=redis_namespace)
    cold_store = PgColdStore(database_url=taskplane_database_url)
    store = DualLayerStore(hot_store=hot_store, cold_store=cold_store)
    await store.save_envelope(_envelope())
    await store.save_ticket(_ticket("ticket-async", priority=2))

    async def _cold_has_ticket() -> bool:
        return await cold_store.get_ticket("ticket-async") is not None

    try:
        claimed = await store.claim_next(batch_size=1)
        assert [ticket.ticket_id for ticket in claimed] == ["ticket-async"]
        await _wait_until(_cold_has_ticket)
    finally:
        await store.aclose()


async def test_get_ticket_falls_back_to_pg_on_hot_miss(
    taskplane_redis_url: str,
    taskplane_database_url: str,
    redis_namespace: str,
    pg_isolated_tables: None,
) -> None:
    from autospider.legacy.taskplane.store.dual_store import DualLayerStore
    from autospider.legacy.taskplane.store.pg_store import PgColdStore
    from autospider.legacy.taskplane.store.redis_store import RedisHotStore

    hot_store = RedisHotStore(redis_url=taskplane_redis_url, namespace=redis_namespace)
    cold_store = PgColdStore(database_url=taskplane_database_url)
    store = DualLayerStore(hot_store=hot_store, cold_store=cold_store)
    await store.save_envelope(_envelope())
    await store.save_ticket(_ticket("ticket-fallback"))

    async def _cold_has_ticket() -> bool:
        return await cold_store.get_ticket("ticket-fallback") is not None

    await _wait_until(_cold_has_ticket)
    await hot_store.delete_ticket("ticket-fallback")
    restored = await store.get_ticket("ticket-fallback")

    try:
        assert restored is not None
        assert restored.ticket_id == "ticket-fallback"
        assert restored.status == TicketStatus.QUEUED
    finally:
        await store.aclose()


async def test_save_result_is_durable_in_pg(
    taskplane_redis_url: str,
    taskplane_database_url: str,
    redis_namespace: str,
    pg_isolated_tables: None,
) -> None:
    from autospider.legacy.taskplane.store.dual_store import DualLayerStore
    from autospider.legacy.taskplane.store.pg_store import PgColdStore
    from autospider.legacy.taskplane.store.redis_store import RedisHotStore

    hot_store = RedisHotStore(redis_url=taskplane_redis_url, namespace=redis_namespace)
    cold_store = PgColdStore(database_url=taskplane_database_url)
    store = DualLayerStore(hot_store=hot_store, cold_store=cold_store)
    await store.save_envelope(_envelope())
    await store.save_ticket(_ticket("ticket-result"))
    await store.update_status("ticket-result", TicketStatus.RUNNING, assigned_to="dual-worker")

    result = TaskResult(
        result_id="result-dual",
        ticket_id="ticket-result",
        status=ResultStatus.SUCCESS,
        output={"items": 7},
    )
    await store.save_result(result)
    await store.update_status("ticket-result", TicketStatus.COMPLETED, assigned_to="dual-worker")

    try:
        stored_result = await cold_store.get_result("ticket-result")
        assert stored_result is not None
        assert stored_result.output == {"items": 7}
    finally:
        await store.aclose()

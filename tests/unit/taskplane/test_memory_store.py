import pytest

from autospider.taskplane.protocol import (
    PlanEnvelope,
    ResultStatus,
    TaskResult,
    TaskTicket,
    TicketStatus,
)
from autospider.taskplane.store.memory_store import MemoryStore
from autospider.taskplane.strategy import PriorityStrategy


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore(strategy=PriorityStrategy())


@pytest.fixture
def envelope() -> PlanEnvelope:
    return PlanEnvelope(envelope_id="e1", source_agent="test")


@pytest.fixture
def ticket() -> TaskTicket:
    return TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)


class TestMemoryStoreEnvelope:
    async def test_save_and_get(self, store: MemoryStore, envelope: PlanEnvelope) -> None:
        await store.save_envelope(envelope)
        got = await store.get_envelope("e1")

        assert got is not None
        assert got.envelope_id == "e1"

    async def test_get_missing(self, store: MemoryStore) -> None:
        assert await store.get_envelope("missing") is None


class TestMemoryStoreTicket:
    async def test_save_and_get(self, store: MemoryStore, ticket: TaskTicket) -> None:
        await store.save_ticket(ticket)
        got = await store.get_ticket("t1")

        assert got is not None
        assert got.ticket_id == "t1"

    async def test_batch_save(self, store: MemoryStore) -> None:
        tickets = [
            TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED),
            TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.QUEUED),
        ]

        await store.save_tickets_batch(tickets)

        assert await store.get_ticket("t1") is not None
        assert await store.get_ticket("t2") is not None

    async def test_update_status(self, store: MemoryStore, ticket: TaskTicket) -> None:
        await store.save_ticket(ticket)
        updated = await store.update_status("t1", TicketStatus.DISPATCHED)
        assert updated.status == TicketStatus.DISPATCHED

    async def test_get_by_envelope(self, store: MemoryStore) -> None:
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)
        t2 = TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.QUEUED)
        t3 = TaskTicket(ticket_id="t3", envelope_id="e2", status=TicketStatus.QUEUED)

        await store.save_tickets_batch([t1, t2, t3])
        result = await store.get_tickets_by_envelope("e1")
        assert len(result) == 2


class TestMemoryStoreClaim:
    async def test_claim_returns_highest_priority(self, store: MemoryStore) -> None:
        low = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED, priority=5)
        high = TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.QUEUED, priority=0)

        await store.save_tickets_batch([low, high])
        claimed = await store.claim_next(batch_size=1)

        assert len(claimed) == 1
        assert claimed[0].ticket_id == "t2"

    async def test_claim_empty_queue(self, store: MemoryStore) -> None:
        assert await store.claim_next(batch_size=1) == []

    async def test_claim_respects_batch_size(self, store: MemoryStore) -> None:
        for index in range(5):
            queued = TaskTicket(
                ticket_id=f"t{index}",
                envelope_id="e1",
                status=TicketStatus.QUEUED,
            )
            await store.save_ticket(queued)

        claimed = await store.claim_next(batch_size=3)
        assert len(claimed) == 3

    async def test_release_claim(self, store: MemoryStore) -> None:
        queued = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)

        await store.save_ticket(queued)
        await store.claim_next(batch_size=1)
        await store.release_claim("t1", reason="retry")

        got = await store.get_ticket("t1")
        assert got is not None
        assert got.status == TicketStatus.QUEUED


class TestMemoryStoreResult:
    async def test_save_and_get_result(self, store: MemoryStore) -> None:
        result = TaskResult(result_id="r1", ticket_id="t1", status=ResultStatus.SUCCESS)

        await store.save_result(result)
        got = await store.get_result("t1")

        assert got is not None
        assert got.result_id == "r1"

    async def test_get_missing_result(self, store: MemoryStore) -> None:
        assert await store.get_result("missing") is None


class TestMemoryStoreQuery:
    async def test_query_by_status(self, store: MemoryStore) -> None:
        queued = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)
        done = TaskTicket(ticket_id="t2", envelope_id="e1", status=TicketStatus.COMPLETED)

        await store.save_tickets_batch([queued, done])
        result = await store.query_tickets(status=TicketStatus.QUEUED)

        assert len(result) == 1
        assert result[0].ticket_id == "t1"

    async def test_query_by_envelope(self, store: MemoryStore) -> None:
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1", status=TicketStatus.QUEUED)
        t2 = TaskTicket(ticket_id="t2", envelope_id="e2", status=TicketStatus.QUEUED)

        await store.save_tickets_batch([t1, t2])
        result = await store.query_tickets(envelope_id="e1")
        assert len(result) == 1

    async def test_query_by_labels(self, store: MemoryStore) -> None:
        t1 = TaskTicket(
            ticket_id="t1",
            envelope_id="e1",
            status=TicketStatus.QUEUED,
            labels={"mode": "collect"},
        )
        t2 = TaskTicket(
            ticket_id="t2",
            envelope_id="e1",
            status=TicketStatus.QUEUED,
            labels={"mode": "expand"},
        )

        await store.save_tickets_batch([t1, t2])
        result = await store.query_tickets(labels={"mode": "collect"})

        assert len(result) == 1
        assert result[0].ticket_id == "t1"

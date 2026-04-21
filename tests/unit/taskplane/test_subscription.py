import asyncio

import pytest

from autospider.composition.taskplane.protocol import PlanEnvelope, ResultStatus, TaskResult, TaskTicket
from autospider.composition.taskplane.scheduler import TaskScheduler
from autospider.composition.taskplane.store.memory_store import MemoryStore
from autospider.composition.taskplane.subscription import Subscription


@pytest.fixture
def scheduler() -> TaskScheduler:
    return TaskScheduler(store=MemoryStore())


class TestSubscription:
    async def test_processes_all_tickets(self, scheduler: TaskScheduler) -> None:
        tickets = [TaskTicket(ticket_id=f"t{index}", envelope_id="e1") for index in range(3)]
        envelope = PlanEnvelope(envelope_id="e1", source_agent="test", tickets=tickets)
        processed: list[str] = []

        async def handler(ticket: TaskTicket) -> TaskResult:
            processed.append(ticket.ticket_id)
            return TaskResult(
                result_id=f"r-{ticket.ticket_id}",
                ticket_id=ticket.ticket_id,
                status=ResultStatus.SUCCESS,
            )

        await scheduler.submit_envelope(envelope)
        subscription = Subscription(
            scheduler=scheduler,
            handler=handler,
            concurrency=2,
            poll_interval=0.05,
        )

        await subscription.start()
        await asyncio.sleep(0.5)
        await subscription.stop()

        assert len(processed) == 3

    async def test_stops_gracefully(self, scheduler: TaskScheduler) -> None:
        subscription = Subscription(
            scheduler=scheduler,
            handler=lambda ticket: TaskResult(
                result_id="r",
                ticket_id=ticket.ticket_id,
                status=ResultStatus.SUCCESS,
            ),
            concurrency=1,
            poll_interval=0.05,
        )

        await subscription.start()
        await asyncio.sleep(0.1)
        await subscription.stop()


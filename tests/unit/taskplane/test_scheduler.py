import pytest

from autospider.composition.taskplane.protocol import (
    PlanEnvelope,
    ResultStatus,
    TaskResult,
    TaskTicket,
    TicketStatus,
)
from autospider.composition.taskplane.scheduler import TaskScheduler
from autospider.composition.taskplane.store.memory_store import MemoryStore
from autospider.composition.taskplane.subscription import Subscription


@pytest.fixture
def scheduler() -> TaskScheduler:
    return TaskScheduler(store=MemoryStore())


def _envelope(ticket_count: int = 3) -> PlanEnvelope:
    tickets = [
        TaskTicket(ticket_id=f"t{index}", envelope_id="e1", payload={"index": index})
        for index in range(ticket_count)
    ]
    return PlanEnvelope(envelope_id="e1", source_agent="test", tickets=tickets)


class TestSubmit:
    async def test_submit_envelope(self, scheduler: TaskScheduler) -> None:
        receipt = await scheduler.submit_envelope(_envelope(3))
        assert receipt.envelope_id == "e1"
        assert receipt.ticket_count == 3

    async def test_tickets_become_queued_after_submit(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(2))
        ticket = await scheduler.get_ticket("t0")
        assert ticket is not None
        assert ticket.status == TicketStatus.QUEUED

    async def test_submit_additional_tickets(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(1))
        ids = await scheduler.submit_tickets(
            "e1", [TaskTicket(ticket_id="t_new", envelope_id="e1")]
        )
        assert ids == ["t_new"]

    def test_subscribe_returns_subscription(self, scheduler: TaskScheduler) -> None:
        async def handler(ticket: TaskTicket) -> TaskResult:
            return TaskResult(
                result_id=f"r-{ticket.ticket_id}",
                ticket_id=ticket.ticket_id,
                status=ResultStatus.SUCCESS,
            )

        subscription = scheduler.subscribe(handler, concurrency=2)
        assert isinstance(subscription, Subscription)


class TestPullAndReport:
    async def test_pull_returns_tickets(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(3))
        pulled = await scheduler.pull(batch_size=2)
        assert len(pulled) == 2

    async def test_ack_start_transitions_to_running(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)

        await scheduler.ack_start(pulled[0].ticket_id, agent_id="worker-1")
        ticket = await scheduler.get_ticket(pulled[0].ticket_id)

        assert ticket is not None
        assert ticket.status == TicketStatus.RUNNING

    async def test_report_success(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)

        await scheduler.ack_start(pulled[0].ticket_id)
        receipt = await scheduler.report_result(
            TaskResult(
                result_id="r1",
                ticket_id=pulled[0].ticket_id,
                status=ResultStatus.SUCCESS,
            )
        )

        assert receipt.final_status == TicketStatus.COMPLETED
        assert not receipt.retried

    async def test_report_failure_retries(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)

        await scheduler.ack_start(pulled[0].ticket_id)
        receipt = await scheduler.report_result(
            TaskResult(
                result_id="r1",
                ticket_id=pulled[0].ticket_id,
                status=ResultStatus.FAILED,
                error="timeout",
            )
        )

        ticket = await scheduler.get_ticket(pulled[0].ticket_id)
        assert receipt.retried
        assert receipt.final_status == TicketStatus.QUEUED
        assert ticket is not None
        assert ticket.attempt_count == 1

    async def test_report_failure_exhausts_retries(self, scheduler: TaskScheduler) -> None:
        envelope = PlanEnvelope(
            envelope_id="e1",
            source_agent="test",
            tickets=[TaskTicket(ticket_id="t0", envelope_id="e1", max_attempts=1)],
        )

        await scheduler.submit_envelope(envelope)
        pulled = await scheduler.pull(batch_size=1)
        await scheduler.ack_start(pulled[0].ticket_id)

        receipt = await scheduler.report_result(
            TaskResult(result_id="r1", ticket_id="t0", status=ResultStatus.FAILED)
        )

        assert receipt.final_status == TicketStatus.FAILED
        assert not receipt.retried

    async def test_report_expanded_spawns_tickets(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)

        await scheduler.ack_start(pulled[0].ticket_id)
        receipt = await scheduler.report_result(
            TaskResult(
                result_id="r1",
                ticket_id=pulled[0].ticket_id,
                status=ResultStatus.EXPANDED,
                spawned_tickets=[
                    {"ticket_id": "child1", "envelope_id": "e1", "payload": {"x": 1}},
                    {"ticket_id": "child2", "envelope_id": "e1", "payload": {"x": 2}},
                ],
            )
        )

        child = await scheduler.get_ticket("child1")
        assert receipt.final_status == TicketStatus.EXPANDED
        assert receipt.spawned_count == 2
        assert child is not None
        assert child.status == TicketStatus.QUEUED


class TestEnvelopeProgress:
    async def test_progress_counts(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(3))
        progress = await scheduler.get_envelope_progress("e1")

        assert progress.total == 3
        assert progress.queued == 3
        assert progress.completed == 0


class TestCancel:
    async def test_cancel_ticket(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(1))
        await scheduler.cancel_ticket("t0")

        ticket = await scheduler.get_ticket("t0")
        assert ticket is not None
        assert ticket.status == TicketStatus.CANCELLED

    async def test_cancel_envelope(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(3))
        await scheduler.cancel_envelope("e1")

        progress = await scheduler.get_envelope_progress("e1")
        assert progress.cancelled == 3


class TestRelease:
    async def test_release_returns_to_queue(self, scheduler: TaskScheduler) -> None:
        await scheduler.submit_envelope(_envelope(1))
        pulled = await scheduler.pull(batch_size=1)

        await scheduler.release(pulled[0].ticket_id, reason="manual")
        ticket = await scheduler.get_ticket(pulled[0].ticket_id)

        assert ticket is not None
        assert ticket.status == TicketStatus.QUEUED


class TestLifecycle:
    async def test_aclose_marks_scheduler_closed(self, scheduler: TaskScheduler) -> None:
        await scheduler.aclose()
        assert scheduler.is_closed

    async def test_closed_scheduler_rejects_operations(self, scheduler: TaskScheduler) -> None:
        await scheduler.aclose()
        with pytest.raises(RuntimeError, match="task_scheduler_closed"):
            await scheduler.pull(batch_size=1)


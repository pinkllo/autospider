from autospider.composition.taskplane.protocol import (
    PlanEnvelope,
    ResultStatus,
    TaskResult,
    TaskTicket,
    TicketStatus,
)


class TestTicketStatus:
    def test_all_values_exist(self):
        expected = {
            "registered",
            "queued",
            "dispatched",
            "running",
            "completed",
            "failed",
            "expanded",
            "timeout",
            "cancelled",
        }
        assert {status.value for status in TicketStatus} == expected

    def test_terminal_states(self):
        assert TicketStatus.COMPLETED.is_terminal
        assert TicketStatus.FAILED.is_terminal
        assert TicketStatus.CANCELLED.is_terminal
        assert TicketStatus.EXPANDED.is_terminal

    def test_non_terminal_states(self):
        assert not TicketStatus.REGISTERED.is_terminal
        assert not TicketStatus.QUEUED.is_terminal
        assert not TicketStatus.RUNNING.is_terminal

    def test_valid_transition_registered_to_queued(self):
        assert TicketStatus.REGISTERED.can_transition_to(TicketStatus.QUEUED)

    def test_invalid_transition_completed_to_running(self):
        assert not TicketStatus.COMPLETED.can_transition_to(TicketStatus.RUNNING)

    def test_valid_transition_running_to_failed(self):
        assert TicketStatus.RUNNING.can_transition_to(TicketStatus.FAILED)

    def test_valid_transition_failed_to_queued_retry(self):
        assert TicketStatus.FAILED.can_transition_to(TicketStatus.QUEUED)


class TestResultStatus:
    def test_all_values_exist(self):
        assert {status.value for status in ResultStatus} == {"success", "failed", "expanded"}


class TestTaskTicket:
    def test_create_minimal(self):
        ticket = TaskTicket(ticket_id="t1", envelope_id="e1")
        assert ticket.ticket_id == "t1"
        assert ticket.status == TicketStatus.REGISTERED
        assert ticket.priority == 0
        assert ticket.payload == {}
        assert ticket.attempt_count == 0
        assert ticket.max_attempts == 3

    def test_create_with_payload(self):
        ticket = TaskTicket(
            ticket_id="t1",
            envelope_id="e1",
            payload={"url": "https://example.com"},
            labels={"mode": "collect"},
            priority=5,
        )
        assert ticket.payload["url"] == "https://example.com"
        assert ticket.labels["mode"] == "collect"
        assert ticket.priority == 5

    def test_roundtrip_serialization(self):
        ticket = TaskTicket(ticket_id="t1", envelope_id="e1", payload={"x": 1})
        restored = TaskTicket.model_validate(ticket.model_dump(mode="python"))
        assert restored.ticket_id == "t1"
        assert restored.payload == {"x": 1}


class TestPlanEnvelope:
    def test_create_with_tickets(self):
        t1 = TaskTicket(ticket_id="t1", envelope_id="e1")
        t2 = TaskTicket(ticket_id="t2", envelope_id="e1")
        envelope = PlanEnvelope(
            envelope_id="e1",
            source_agent="planner",
            tickets=[t1, t2],
        )
        assert len(envelope.tickets) == 2
        assert envelope.source_agent == "planner"

    def test_empty_envelope(self):
        envelope = PlanEnvelope(envelope_id="e1", source_agent="test")
        assert envelope.tickets == []
        assert envelope.plan_snapshot == {}


class TestTaskResult:
    def test_create_success(self):
        result = TaskResult(
            result_id="r1",
            ticket_id="t1",
            status=ResultStatus.SUCCESS,
            output={"items": 42},
        )
        assert result.status == ResultStatus.SUCCESS
        assert result.output["items"] == 42
        assert result.error == ""
        assert result.spawned_tickets == []

    def test_create_expanded(self):
        result = TaskResult(
            result_id="r2",
            ticket_id="t1",
            status=ResultStatus.EXPANDED,
            spawned_tickets=[{"ticket_id": "t1-child1", "payload": {}}],
        )
        assert len(result.spawned_tickets) == 1


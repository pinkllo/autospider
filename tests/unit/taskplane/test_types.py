from autospider.composition.taskplane.protocol import TicketStatus
from autospider.composition.taskplane.types import (
    EnvelopeProgress,
    ReportReceipt,
    SubmitReceipt,
    TaskPlaneConfig,
)


class TestSubmitReceipt:
    def test_fields(self):
        receipt = SubmitReceipt(envelope_id="e1", ticket_count=5)
        assert receipt.envelope_id == "e1"
        assert receipt.ticket_count == 5
        assert receipt.queued_at is not None


class TestReportReceipt:
    def test_fields(self):
        receipt = ReportReceipt(
            ticket_id="t1",
            final_status=TicketStatus.COMPLETED,
            retried=False,
            spawned_count=0,
        )
        assert receipt.final_status == TicketStatus.COMPLETED


class TestEnvelopeProgress:
    def test_fields(self):
        progress = EnvelopeProgress(envelope_id="e1", total=10, completed=3, failed=1)
        assert progress.total == 10
        assert progress.queued == 0


class TestTaskPlaneConfig:
    def test_defaults(self):
        config = TaskPlaneConfig()
        assert config.redis_url == ""
        assert config.default_max_attempts == 3
        assert config.default_timeout_seconds == 600
        assert config.fallback_to_memory is True


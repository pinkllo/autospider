from autospider.contexts.planning.domain import SubTask
from autospider.composition.legacy.taskplane_adapter.subtask_bridge import SubtaskBridge


def _sample_subtask() -> SubTask:
    return SubTask(
        id="s1",
        name="招标公告",
        list_url="https://example.com/zb",
        task_description="采集招标公告列表",
        priority=2,
        depth=1,
    )


class TestSubtaskBridge:
    def test_to_ticket(self) -> None:
        ticket = SubtaskBridge.to_ticket(_sample_subtask(), envelope_id="e1")

        assert ticket.ticket_id == "s1"
        assert ticket.envelope_id == "e1"
        assert ticket.priority == 2
        assert ticket.labels["depth"] == "1"
        assert ticket.payload["list_url"] == "https://example.com/zb"

    def test_from_ticket(self) -> None:
        restored = SubtaskBridge.from_ticket(
            SubtaskBridge.to_ticket(_sample_subtask(), envelope_id="e1")
        )

        assert restored.id == "s1"
        assert restored.name == "招标公告"
        assert restored.list_url == "https://example.com/zb"

    def test_roundtrip(self) -> None:
        subtask = _sample_subtask()
        restored = SubtaskBridge.from_ticket(SubtaskBridge.to_ticket(subtask, envelope_id="e1"))

        assert restored.task_description == subtask.task_description
        assert restored.priority == subtask.priority

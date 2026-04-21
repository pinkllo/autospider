from autospider.contexts.planning.domain import SubTask, TaskPlan
from autospider.composition.taskplane_adapter.plan_bridge import PlanBridge


def _sample_plan() -> TaskPlan:
    return TaskPlan(
        plan_id="plan-001",
        original_request="采集招标公告",
        site_url="https://example.com",
        subtasks=[
            SubTask(
                id="s1",
                name="招标公告",
                list_url="https://example.com/zb",
                task_description="采集招标公告列表",
            ),
            SubTask(
                id="s2",
                name="中标公告",
                list_url="https://example.com/zb2",
                task_description="采集中标公告列表",
            ),
        ],
        shared_fields=[{"name": "title", "description": "标题"}],
    )


class TestPlanBridge:
    def test_to_envelope(self) -> None:
        envelope = PlanBridge.to_envelope(_sample_plan(), source_agent="plan_node")

        assert envelope.envelope_id == "plan-001"
        assert envelope.source_agent == "plan_node"
        assert len(envelope.tickets) == 2
        assert envelope.tickets[0].ticket_id == "s1"
        assert envelope.plan_snapshot["original_request"] == "采集招标公告"

    def test_from_envelope(self) -> None:
        restored = PlanBridge.from_envelope(PlanBridge.to_envelope(_sample_plan()))
        assert restored.plan_id == "plan-001"
        assert len(restored.subtasks) == 2

    def test_roundtrip(self) -> None:
        plan = _sample_plan()
        restored = PlanBridge.from_envelope(PlanBridge.to_envelope(plan))

        assert restored.original_request == plan.original_request
        assert restored.site_url == plan.site_url


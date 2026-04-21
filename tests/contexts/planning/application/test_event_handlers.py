from __future__ import annotations

from autospider.contexts.planning.application.dto import TaskClarifiedEventDTO
from autospider.contexts.planning.application.event_handlers import TaskClarifiedHandler
from autospider.contexts.planning.domain.model import TaskPlan
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


class _FakeRepository:
    def build_plan(self, subtasks, *, nodes=None, journal=None) -> TaskPlan:
        return TaskPlan(
            plan_id="plan-1",
            original_request="采集招标公告",
            site_url="https://example.com/bids",
            subtasks=list(subtasks),
            nodes=list(nodes or []),
            journal=list(journal or []),
            total_subtasks=len(subtasks),
            created_at="created-at",
            updated_at="updated-at",
        )

    def create_empty_plan(self) -> TaskPlan:
        return self.build_plan([])

    def save_plan(self, plan: TaskPlan) -> TaskPlan:
        return plan


def test_task_clarified_handler_accepts_planning_local_event_dto() -> None:
    recorded: dict[str, str] = {}

    def _factory(*, site_url: str, user_request: str, output_dir: str) -> _FakeRepository:
        recorded.update(
            {
                "site_url": site_url,
                "user_request": user_request,
                "output_dir": output_dir,
            }
        )
        return _FakeRepository()

    payload = TaskClarifiedEventDTO(
        session_id="session-1",
        output_dir="output/test",
        task={
            "intent": "招标公告",
            "list_url": "https://example.com/bids",
            "task_description": "采集招标公告",
            "fields": [{"name": "title"}],
            "max_pages": 2,
        },
    )

    set_run_context(run_id="run-test", trace_id="trace-test")
    try:
        result = TaskClarifiedHandler(_factory).handle(payload)
    finally:
        clear_run_context()

    assert result.status == "success"
    assert recorded == {
        "site_url": "https://example.com/bids",
        "user_request": "采集招标公告",
        "output_dir": "output/test",
    }
    assert result.data.site_url == "https://example.com/bids"
    assert result.data.original_request == "采集招标公告"

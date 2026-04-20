from __future__ import annotations

import pytest

from autospider.composition.container import CompositionContainer
from autospider.contexts.planning.infrastructure.publishers import PLANNING_EVENTS_STREAM
from autospider.contexts.planning.domain.model import TaskPlan
from autospider.platform.messaging.in_memory import InMemoryMessaging
from autospider.platform.persistence.redis.keys import subtask_queue_key


class _InMemoryPlanRepository:
    def __init__(self, *, site_url: str, user_request: str) -> None:
        self._site_url = site_url
        self._user_request = user_request
        self.saved_plan: TaskPlan | None = None

    def build_plan(self, subtasks, *, nodes=None, journal=None):
        return TaskPlan(
            plan_id="plan-memory-1",
            original_request=self._user_request,
            site_url=self._site_url,
            subtasks=list(subtasks),
            nodes=list(nodes or []),
            journal=list(journal or []),
            total_subtasks=len(list(subtasks)),
            created_at="2026-04-20T00:00:00+08:00",
            updated_at="2026-04-20T00:00:00+08:00",
        )

    def create_empty_plan(self):
        return self.build_plan([])

    def save_plan(self, plan: TaskPlan):
        self.saved_plan = plan
        return plan


def _plan_repository_factory(registry: dict[str, _InMemoryPlanRepository]):
    def _factory(*, site_url: str, user_request: str, output_dir: str):
        del output_dir
        repository = _InMemoryPlanRepository(site_url=site_url, user_request=user_request)
        registry["repository"] = repository
        return repository

    return _factory


async def _collect_events(messaging, stream: str) -> list[object]:
    return [
        event
        async for event in messaging.subscribe(
            stream,
            "assertions",
            "consumer-1",
            block_ms=0,
            batch=10,
        )
    ]


@pytest.mark.asyncio
async def test_chat_task_clarified_event_creates_plan_and_queue_message() -> None:
    messaging = InMemoryMessaging()
    registry: dict[str, _InMemoryPlanRepository] = {}
    container = CompositionContainer(
        messaging=messaging,
        plan_repository_factory=_plan_repository_factory(registry),
    )

    await container.chat_publisher.publish_task_clarified(
        session_id="session-1",
        task={
            "intent": "collect",
            "list_url": "https://example.com/notices",
            "task_description": "采集公告列表",
            "fields": [{"name": "title", "description": "公告标题", "required": True}],
            "target_url_count": 5,
        },
        trace_id="trace-1",
        run_id="run-1",
        output_dir="output/test-run-1",
    )

    processed = await container.pump("planning.task_clarified")

    planning_events = await _collect_events(messaging, PLANNING_EVENTS_STREAM)
    queue_events = await _collect_events(messaging, subtask_queue_key())

    assert processed == 1
    assert [event.type for event in planning_events] == [
        "planning.PlanCreated",
        "planning.SubTaskPlanned",
    ]
    assert queue_events[0].type == "queue.SubTaskDispatchRequested"
    assert queue_events[0].payload["plan_id"]
    assert registry["repository"].saved_plan is not None

    await container.close()

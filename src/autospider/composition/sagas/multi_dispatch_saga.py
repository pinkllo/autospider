from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from autospider.contexts.planning.application.dto import TaskPlanDTO
from autospider.contexts.planning.infrastructure.publishers import PlanningEventPublisher
from autospider.platform.messaging.ports import Event, Messaging
from autospider.platform.persistence.redis.keys import subtask_queue_key

QUEUE_DISPATCH_EVENT = "queue.SubTaskDispatchRequested"


class MultiDispatchSaga:
    def __init__(self, messaging: Messaging, planning_publisher: PlanningEventPublisher) -> None:
        self._messaging = messaging
        self._planning_publisher = planning_publisher

    async def dispatch_plan(
        self,
        *,
        plan: TaskPlanDTO,
        trace_id: str,
        run_id: str | None = None,
        output_dir: str = "output",
    ) -> tuple[str, ...]:
        published: list[str] = []
        for raw_subtask in list(plan.subtasks):
            await self._planning_publisher.publish_subtask_planned(
                plan_id=plan.plan_id,
                subtask=dict(raw_subtask),
                trace_id=trace_id,
                run_id=run_id,
                output_dir=output_dir,
            )
            published.append(
                await self._publish_queue_event(
                    plan_id=plan.plan_id,
                    subtask=dict(raw_subtask),
                    trace_id=trace_id,
                    run_id=run_id,
                    output_dir=output_dir,
                )
            )
        return tuple(published)

    async def _publish_queue_event(
        self,
        *,
        plan_id: str,
        subtask: dict[str, Any],
        trace_id: str,
        run_id: str | None,
        output_dir: str,
    ) -> str:
        payload = {"plan_id": plan_id, "subtask": subtask, "output_dir": output_dir}
        event = Event(
            type=QUEUE_DISPATCH_EVENT,
            run_id=run_id,
            trace_id=trace_id,
            occurred_at=datetime.now(timezone.utc),
            payload=payload,
        )
        return await self._messaging.publish(subtask_queue_key(), event)

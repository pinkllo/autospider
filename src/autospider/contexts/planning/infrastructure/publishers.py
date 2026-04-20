from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autospider.contexts.planning.application.dto import TaskPlanDTO
from autospider.platform.messaging.ports import Event, Messaging
from autospider.platform.persistence.redis.keys import events_stream_key

PLANNING_EVENTS_STREAM = events_stream_key("planning")
PLAN_CREATED_EVENT = "planning.PlanCreated"
SUBTASK_PLANNED_EVENT = "planning.SubTaskPlanned"


class PlanCreatedPayload(BaseModel):
    plan: dict[str, Any]
    output_dir: str = "output"


class SubTaskPlannedPayload(BaseModel):
    plan_id: str
    subtask: dict[str, Any] = Field(default_factory=dict)
    output_dir: str = "output"


class PlanningEventPublisher:
    def __init__(self, messaging: Messaging) -> None:
        self._messaging = messaging

    async def publish_plan_created(
        self,
        *,
        plan: TaskPlanDTO,
        trace_id: str,
        run_id: str | None = None,
        output_dir: str = "output",
    ) -> str:
        payload = PlanCreatedPayload(plan=plan.model_dump(mode="python"), output_dir=output_dir)
        return await self._publish(
            event_type=PLAN_CREATED_EVENT,
            payload=payload.model_dump(mode="python"),
            trace_id=trace_id,
            run_id=run_id,
        )

    async def publish_subtask_planned(
        self,
        *,
        plan_id: str,
        subtask: dict[str, Any],
        trace_id: str,
        run_id: str | None = None,
        output_dir: str = "output",
    ) -> str:
        payload = SubTaskPlannedPayload(
            plan_id=plan_id, subtask=dict(subtask), output_dir=output_dir
        )
        return await self._publish(
            event_type=SUBTASK_PLANNED_EVENT,
            payload=payload.model_dump(mode="python"),
            trace_id=trace_id,
            run_id=run_id,
        )

    async def _publish(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        trace_id: str,
        run_id: str | None,
    ) -> str:
        event = Event(
            type=event_type,
            run_id=run_id,
            trace_id=trace_id,
            occurred_at=datetime.now(timezone.utc),
            payload=payload,
        )
        return await self._messaging.publish(PLANNING_EVENTS_STREAM, event)

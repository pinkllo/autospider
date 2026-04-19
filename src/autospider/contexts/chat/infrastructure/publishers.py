from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autospider.contexts.chat.domain.model import ClarifiedTask
from autospider.platform.messaging.ports import Event, Messaging
from autospider.platform.persistence.redis.keys import events_stream_key

CHAT_EVENTS_STREAM = events_stream_key("chat")
TASK_CLARIFIED_EVENT = "chat.TaskClarified"


class TaskClarifiedPayload(BaseModel):
    session_id: str
    output_dir: str = "output"
    task: dict[str, Any] = Field(default_factory=dict)


class ChatEventPublisher:
    def __init__(self, messaging: Messaging) -> None:
        self._messaging = messaging

    async def publish_task_clarified(
        self,
        *,
        session_id: str,
        task: ClarifiedTask | BaseModel | dict[str, Any],
        trace_id: str,
        run_id: str | None = None,
        output_dir: str = "output",
    ) -> str:
        payload = TaskClarifiedPayload(
            session_id=session_id,
            output_dir=output_dir,
            task=_task_payload(task),
        )
        event = Event(
            type=TASK_CLARIFIED_EVENT,
            run_id=run_id,
            trace_id=trace_id,
            occurred_at=datetime.now(timezone.utc),
            payload=payload.model_dump(mode="python"),
        )
        return await self._messaging.publish(CHAT_EVENTS_STREAM, event)


def _task_payload(task: ClarifiedTask | BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(task, ClarifiedTask):
        return task.to_payload()
    if isinstance(task, BaseModel):
        return task.model_dump(mode="python")
    return dict(task)

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from autospider.platform.messaging.ports import Event, Messaging
from autospider.platform.persistence.redis.keys import events_stream_key

EXPERIENCE_EVENTS_STREAM = events_stream_key("experience")
SKILL_SEDIMENTED_EVENT = "experience.SkillSedimented"


class SkillSedimentedPayload(BaseModel):
    skill_path: str
    source_run_id: str = ""


class ExperienceEventPublisher:
    def __init__(self, messaging: Messaging) -> None:
        self._messaging = messaging

    async def publish_skill_sedimented(
        self,
        payload: SkillSedimentedPayload,
        *,
        trace_id: str,
        run_id: str | None = None,
    ) -> str:
        event = Event(
            type=SKILL_SEDIMENTED_EVENT,
            run_id=run_id or payload.source_run_id or None,
            trace_id=trace_id,
            occurred_at=datetime.now(timezone.utc),
            payload=payload.model_dump(mode="python"),
        )
        return await self._messaging.publish(EXPERIENCE_EVENTS_STREAM, event)

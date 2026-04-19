from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from autospider.platform.messaging.ports import Event, Messaging
from autospider.platform.persistence.redis.keys import events_stream_key

COLLECTION_EVENTS_STREAM = events_stream_key("collection")
COLLECTION_FINALIZED_EVENT = "collection.CollectionFinalized"


class CollectionFinalizedEventPayload(BaseModel):
    run_id: str = ""
    plan_id: str = ""
    status: str = ""
    artifacts_dir: str


class CollectionEventPublisher:
    def __init__(self, messaging: Messaging) -> None:
        self._messaging = messaging

    async def publish_collection_finalized(
        self,
        payload: CollectionFinalizedEventPayload,
        *,
        trace_id: str,
        run_id: str | None = None,
    ) -> str:
        event = Event(
            type=COLLECTION_FINALIZED_EVENT,
            run_id=run_id or payload.run_id or None,
            trace_id=trace_id,
            occurred_at=datetime.now(timezone.utc),
            payload=payload.model_dump(mode="python"),
        )
        return await self._messaging.publish(COLLECTION_EVENTS_STREAM, event)

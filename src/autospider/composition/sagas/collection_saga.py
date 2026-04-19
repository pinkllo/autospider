from __future__ import annotations

from dataclasses import dataclass

from autospider.contexts.collection.infrastructure.publishers import (
    CollectionEventPublisher,
    CollectionFinalizedEventPayload,
)


@dataclass(frozen=True, slots=True)
class CollectionSagaState:
    total: int = 0
    completed: int = 0
    failed: int = 0

    @property
    def is_finished(self) -> bool:
        return self.total > 0 and self.completed + self.failed >= self.total


class CollectionSaga:
    def __init__(self, publisher: CollectionEventPublisher) -> None:
        self._publisher = publisher

    def record_result(self, state: CollectionSagaState, *, status: str) -> CollectionSagaState:
        if status == "completed":
            return CollectionSagaState(state.total, state.completed + 1, state.failed)
        if status == "failed":
            return CollectionSagaState(state.total, state.completed, state.failed + 1)
        return state

    async def finalize(
        self,
        payload: CollectionFinalizedEventPayload,
        *,
        trace_id: str,
        run_id: str | None = None,
    ) -> str:
        return await self._publisher.publish_collection_finalized(
            payload,
            trace_id=trace_id,
            run_id=run_id,
        )

from __future__ import annotations

import pytest

from autospider.composition.sagas.collection_saga import CollectionSaga, CollectionSagaState
from autospider.contexts.collection.infrastructure.publishers import (
    COLLECTION_EVENTS_STREAM,
    COLLECTION_FINALIZED_EVENT,
    CollectionEventPublisher,
    CollectionFinalizedEventPayload,
)
from autospider.platform.messaging.in_memory import InMemoryMessaging


async def _collect_first(messaging, stream: str):
    async for event in messaging.subscribe(stream, "assertions", "consumer-1", block_ms=0):
        return event
    raise AssertionError("expected an event")


def test_collection_saga_updates_progress_state() -> None:
    saga = CollectionSaga(CollectionEventPublisher(InMemoryMessaging()))
    state = CollectionSagaState(total=2)

    after_success = saga.record_result(state, status="completed")
    after_failure = saga.record_result(after_success, status="failed")

    assert after_success.completed == 1
    assert after_failure.failed == 1
    assert after_failure.is_finished is True


@pytest.mark.asyncio
async def test_collection_saga_publishes_collection_finalized_event() -> None:
    messaging = InMemoryMessaging()
    saga = CollectionSaga(CollectionEventPublisher(messaging))

    await saga.finalize(
        CollectionFinalizedEventPayload(
            run_id="run-1",
            plan_id="plan-1",
            status="completed",
            artifacts_dir="output/runs/run-1",
        ),
        trace_id="trace-1",
    )

    event = await _collect_first(messaging, COLLECTION_EVENTS_STREAM)

    assert event.type == COLLECTION_FINALIZED_EVENT
    assert event.payload["plan_id"] == "plan-1"

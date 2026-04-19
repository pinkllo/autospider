from __future__ import annotations

import fakeredis.aioredis
import pytest

from autospider.contexts.chat.domain.model import ClarificationSession, DialogueMessage
from autospider.contexts.chat.infrastructure.repositories.session_repository import (
    RedisSessionRepository,
)


@pytest.mark.asyncio
async def test_redis_session_repository_round_trips_session_payload() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    repository = RedisSessionRepository(client)
    session = ClarificationSession(
        session_id="session-1",
        turns=(DialogueMessage(role="user", content="collect products"),),
    )

    await repository.save(session)
    restored = await repository.get("session-1")

    assert restored is not None
    assert restored.session_id == "session-1"
    assert restored.turns[0].content == "collect products"
    await client.aclose()

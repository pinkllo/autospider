from __future__ import annotations

import json

from autospider.contexts.chat.domain.model import ClarificationSession
from autospider.platform.persistence.redis.base_repository import BaseRedisRepository
from autospider.platform.persistence.redis.keys import chat_session_key


class RedisSessionRepository(BaseRedisRepository):
    async def get(self, session_id: str) -> ClarificationSession | None:
        payload = await self.read_hash(chat_session_key(session_id))
        raw_session = str(payload.get("session") or "").strip()
        if not raw_session:
            return None
        return ClarificationSession.from_payload(json.loads(raw_session))

    async def save(self, session: ClarificationSession) -> None:
        serialized = json.dumps(session.to_payload(), ensure_ascii=False)
        await self.write_hash(chat_session_key(session.session_id), {"session": serialized})

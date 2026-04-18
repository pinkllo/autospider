from __future__ import annotations

import fakeredis.aioredis
import pytest

from autospider.platform.persistence.redis.base_repository import BaseRedisRepository


@pytest.mark.asyncio
async def test_base_repository_supports_hash_set_and_list_crud() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    repository = BaseRedisRepository(client)

    await repository.write_hash("run:1", {"status": "running", "count": "1"})
    await repository.add_set_members("skill:index", ["skill-1", "skill-2"])
    await repository.prepend_list("run:1:pages", ["page-1", "page-2"])

    assert await repository.read_hash("run:1") == {"status": "running", "count": "1"}
    assert await repository.read_set("skill:index") == {"skill-1", "skill-2"}
    assert await repository.read_list("run:1:pages") == ["page-2", "page-1"]

    await client.aclose()

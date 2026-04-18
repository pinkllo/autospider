from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class BaseRedisRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def write_hash(self, key: str, mapping: Mapping[str, str]) -> None:
        if mapping:
            await self._client.hset(key, mapping=dict(mapping))

    async def read_hash(self, key: str) -> dict[str, str]:
        payload = await self._client.hgetall(key)
        return {str(name): str(value) for name, value in dict(payload).items()}

    async def add_set_members(self, key: str, members: Sequence[str]) -> int:
        if not members:
            return 0
        return int(await self._client.sadd(key, *list(members)))

    async def read_set(self, key: str) -> set[str]:
        values = await self._client.smembers(key)
        return {str(value) for value in values}

    async def prepend_list(self, key: str, values: Sequence[str]) -> int:
        if not values:
            return 0
        return int(await self._client.lpush(key, *list(values)))

    async def read_list(self, key: str) -> list[str]:
        values = await self._client.lrange(key, 0, -1)
        return [str(value) for value in values]

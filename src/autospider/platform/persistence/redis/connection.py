from __future__ import annotations

from redis import asyncio as redis_asyncio

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class RedisConnectionPool:
    def __init__(
        self,
        redis_url: str = DEFAULT_REDIS_URL,
        *,
        max_connections: int = 20,
        decode_responses: bool = True,
    ) -> None:
        self._pool = redis_asyncio.ConnectionPool.from_url(
            redis_url,
            max_connections=max_connections,
            decode_responses=decode_responses,
        )

    def get_client(self) -> redis_asyncio.Redis:
        return redis_asyncio.Redis.from_pool(self._pool)

    async def close(self) -> None:
        await self._pool.aclose()

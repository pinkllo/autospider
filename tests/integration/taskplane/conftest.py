from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest

from .env_config import (
    load_taskplane_dotenv,
    resolve_taskplane_database_url,
    resolve_taskplane_redis_url,
)

PG_TABLES = ("task_results", "task_tickets", "plan_envelopes")


def _normalize_database_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme != "postgresql":
        return url
    return urlunsplit(
        ("postgresql+psycopg", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    )


async def _drop_taskplane_tables(database_url: str) -> None:
    try:
        sqlalchemy = pytest.importorskip("sqlalchemy")
        ext_asyncio = pytest.importorskip("sqlalchemy.ext.asyncio")
        engine = ext_asyncio.create_async_engine(_normalize_database_url(database_url))
        async with engine.begin() as conn:
            for table_name in PG_TABLES:
                await conn.execute(sqlalchemy.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
    except Exception as exc:
        pytest.skip(f"TaskPlane PG 基础设施不可用: {exc}")
    finally:
        if "engine" in locals():
            await engine.dispose()


async def _clear_taskplane_namespace(redis_url: str, namespace: str) -> None:
    redis_asyncio = pytest.importorskip("redis.asyncio")
    client = redis_asyncio.Redis.from_url(redis_url, decode_responses=True)
    try:
        cursor = 0
        pattern = f"{namespace}:*"
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        pytest.skip(f"TaskPlane Redis 基础设施不可用: {exc}")
    finally:
        await client.aclose()


@pytest.fixture
def taskplane_redis_url() -> str:
    load_taskplane_dotenv()
    redis_url = resolve_taskplane_redis_url()
    if not redis_url:
        pytest.skip("TaskPlane Redis 集成测试已跳过: 未设置 AUTOSPIDER_TASKPLANE_REDIS_URL。")
    pytest.importorskip("redis.asyncio")
    return redis_url


@pytest.fixture
def taskplane_database_url() -> str:
    load_taskplane_dotenv()
    database_url = resolve_taskplane_database_url()
    if not database_url:
        pytest.skip("TaskPlane PG 集成测试已跳过: 未设置 AUTOSPIDER_TASKPLANE_DATABASE_URL。")
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("sqlalchemy.ext.asyncio")
    return database_url


@pytest.fixture
async def redis_namespace(taskplane_redis_url: str) -> AsyncIterator[str]:
    redis_asyncio = pytest.importorskip("redis.asyncio")
    namespace = f"taskplane-it-{uuid.uuid4().hex}"
    client = redis_asyncio.Redis.from_url(taskplane_redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        pytest.skip(f"TaskPlane Redis 基础设施不可用: {exc}")
    await client.aclose()
    yield namespace
    await _clear_taskplane_namespace(taskplane_redis_url, namespace)


@pytest.fixture
async def pg_isolated_tables(taskplane_database_url: str) -> AsyncIterator[None]:
    await _drop_taskplane_tables(taskplane_database_url)
    yield
    await _drop_taskplane_tables(taskplane_database_url)

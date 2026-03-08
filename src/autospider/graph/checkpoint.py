"""LangGraph checkpoint 工具。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import quote

from ..common.config import config

_SETUP_COMPLETE: set[str] = set()


def graph_checkpoint_enabled() -> bool:
    """是否启用 LangGraph checkpoint。"""
    return bool(config.graph_checkpoint.enabled)


def _build_redis_conn_string() -> str:
    checkpoint_config = config.graph_checkpoint
    redis_url = str(checkpoint_config.redis_url or "").strip()
    if redis_url:
        return redis_url

    password = checkpoint_config.password
    auth = f":{quote(password, safe='')}@" if password else ""
    return (
        f"redis://{auth}{checkpoint_config.host}:{checkpoint_config.port}/"
        f"{checkpoint_config.db}"
    )


@asynccontextmanager
async def graph_checkpointer_session() -> AsyncIterator[Any | None]:
    """按需创建 LangGraph checkpointer。"""
    if not graph_checkpoint_enabled():
        yield None
        return

    backend = str(config.graph_checkpoint.backend or "redis").strip().lower()
    if backend != "redis":
        raise RuntimeError(
            f"不支持的 GRAPH_CHECKPOINT_BACKEND: {backend}。当前仅支持 redis。"
        )

    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    except ImportError as exc:  # pragma: no cover - 依赖缺失时由运行环境触发
        raise RuntimeError(
            "已启用 GRAPH_CHECKPOINT_ENABLED，但未安装 redis checkpointer 依赖。"
            "请安装 `langgraph-checkpoint-redis`。"
        ) from exc

    conn_string = _build_redis_conn_string()
    saver_cm = AsyncRedisSaver.from_conn_string(conn_string)
    async with saver_cm as checkpointer:
        if conn_string not in _SETUP_COMPLETE:
            await checkpointer.asetup()
            _SETUP_COMPLETE.add(conn_string)
        yield checkpointer

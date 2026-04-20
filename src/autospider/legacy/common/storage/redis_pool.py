"""统一 Redis 连接池管理。

所有需要 Redis 的模块都应通过此模块获取客户端，
避免各自创建连接导致的资源浪费和管理混乱。
"""

from __future__ import annotations

import atexit
from typing import Any

from autospider.legacy.common.config import config
from autospider.legacy.common.logger import get_logger

logger = get_logger(__name__)


class _SyncPool:
    """同步 Redis 连接池（惰性单例）。"""

    _pool: Any | None = None

    @classmethod
    def get_client(cls) -> Any | None:
        """从连接池获取一个同步 Redis 客户端。"""
        if cls._pool is not None:
            import redis as _redis

            return _redis.Redis(connection_pool=cls._pool)

        if not config.redis.enabled:
            return None

        try:
            import redis as _redis

            cls._pool = _redis.ConnectionPool(
                host=config.redis.host,
                port=config.redis.port,
                password=config.redis.password,
                db=config.redis.db,
                decode_responses=True,
                max_connections=20,
                socket_connect_timeout=2,
            )
            client = _redis.Redis(connection_pool=cls._pool)
            client.ping()
            logger.info(
                "[RedisPool] 同步连接池已就绪: %s:%s (db=%s)",
                config.redis.host,
                config.redis.port,
                config.redis.db,
            )
            return client
        except Exception as exc:
            logger.debug("[RedisPool] 同步连接池初始化失败: %s", exc)
            cls._pool = None
            return None

    @classmethod
    def close(cls) -> None:
        """关闭同步连接池并释放所有连接。"""
        if cls._pool is not None:
            try:
                cls._pool.disconnect()
            except Exception:
                pass
            cls._pool = None
            logger.info("[RedisPool] 同步连接池已关闭")


def get_sync_client() -> Any | None:
    """获取共享的同步 Redis 客户端。

    返回的客户端基于全局连接池，无需调用方管理生命周期。
    Redis 未启用或连接失败时返回 None。
    """
    return _SyncPool.get_client()


def close_sync_pool() -> None:
    """关闭全局同步 Redis 连接池。"""
    _SyncPool.close()


atexit.register(close_sync_pool)

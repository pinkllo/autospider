"""Common Storage 模块。

保持 persistence 为默认轻量导出，Redis 相关能力按需延迟加载，
避免无 Redis 依赖的路径在导入期被强制绑定到可选后端。
"""

from __future__ import annotations

from typing import Any

from .persistence import CollectionConfig, CollectionProgress, ConfigPersistence, ProgressPersistence

__all__ = ["RedisQueueManager", "CollectionConfig", "CollectionProgress", "ConfigPersistence", "ProgressPersistence"]


def __getattr__(name: str) -> Any:
    if name == "RedisQueueManager":
        from .redis_manager import RedisQueueManager

        return RedisQueueManager
    raise AttributeError(f"module 'autospider.common.storage' has no attribute {name!r}")

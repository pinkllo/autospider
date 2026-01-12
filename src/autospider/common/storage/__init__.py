"""Common Storage模块 - 存储层"""

from .redis_manager import RedisManager
from .persistence import (
    CollectionConfig,
    CollectionProgress,
    ConfigPersistence,
    ProgressPersistence,
)

__all__ = [
    "RedisManager",
    "CollectionConfig",
    "CollectionProgress",
    "ConfigPersistence",
    "ProgressPersistence",
]

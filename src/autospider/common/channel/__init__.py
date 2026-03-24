"""URL 通道（内存/文件/Redis）。"""

from __future__ import annotations

from typing import Any

from .base import URLChannel, URLTask
from .file_channel import FileURLChannel
from .memory_channel import MemoryURLChannel

__all__ = ["URLChannel", "URLTask", "MemoryURLChannel", "FileURLChannel", "RedisURLChannel", "create_url_channel"]


def __getattr__(name: str) -> Any:
    if name == "RedisURLChannel":
        from .redis_channel import RedisURLChannel

        return RedisURLChannel
    if name == "create_url_channel":
        from .factory import create_url_channel

        return create_url_channel
    raise AttributeError(f"module 'autospider.common.channel' has no attribute {name!r}")

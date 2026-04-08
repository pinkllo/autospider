"""URL 通道（内存/文件/Redis）。"""

from .base import URLChannel, URLTask
from .factory import create_url_channel
from .file_channel import FileURLChannel
from .memory_channel import MemoryURLChannel
from .redis_channel import RedisURLChannel

__all__ = ["URLChannel", "URLTask", "MemoryURLChannel", "FileURLChannel", "RedisURLChannel", "create_url_channel"]

"""URL 通道（Channel）工厂模块，用于根据配置创建不同类型的任务分发通道。"""

from __future__ import annotations

from pathlib import Path

from ..config import config
from ..storage.redis_manager import RedisQueueManager
from .base import URLChannel
from .memory_channel import MemoryURLChannel
from .file_channel import FileURLChannel
from .redis_channel import RedisURLChannel


def create_url_channel(
    mode: str | None = None,
    output_dir: str = "output",
    redis_manager: RedisQueueManager | None = None,
) -> tuple[URLChannel, RedisQueueManager | None]:
    """根据配置或指定模式创建 URL 通道。

    支持以下模式：
    - 'memory': 基于 asyncio.Queue 的内存队列，适用于单机小型任务。
    - 'file': 基于本地文件的持久化队列。
    - 'redis': 基于 Redis Stream 的分布式队列，支持 ACK 机制和多机协同。

    Args:
        mode: 通道模式 ('memory', 'file', 'redis')。如果为 None，则从全局配置中读取。
        output_dir: 文件模式下保存 URL 和进度文件的目录。
        redis_manager: 可选的 Redis 管理器实例。如果为 None 且模式为 'redis'，将自动创建。

    Returns:
        包含 (URLChannel 实例, RedisQueueManager 实例或 None) 的元组。

    Raises:
        ValueError: 当指定的模式不支持时抛出。
    """
    selected = (mode or config.pipeline.mode).lower().strip()

    if selected == "memory":
        channel = MemoryURLChannel(maxsize=config.pipeline.memory_queue_size)
        return channel, None

    if selected == "file":
        base_dir = Path(output_dir)
        urls_file = base_dir / "urls.txt"
        cursor_file = base_dir / config.pipeline.file_cursor_name
        channel = FileURLChannel(
            urls_file=urls_file,
            cursor_file=cursor_file,
            poll_interval=config.pipeline.file_poll_interval,
        )
        return channel, None

    if selected == "redis":
        manager = redis_manager or RedisQueueManager(
            host=config.redis.host,
            port=config.redis.port,
            password=config.redis.password,
            db=config.redis.db,
            key_prefix=config.redis.key_prefix,
        )
        channel = RedisURLChannel(
            manager=manager,
            consumer_name=config.redis.consumer_name,
            block_ms=config.redis.fetch_block_ms,
            max_retries=config.redis.max_retries,
        )
        return channel, manager

    raise ValueError(f"不支持的流水线模式 (Unsupported pipeline mode): {selected}")

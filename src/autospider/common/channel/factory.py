"""URL channel factory."""

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
    """Create a URL channel based on config."""
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

    raise ValueError(f"Unsupported pipeline mode: {selected}")

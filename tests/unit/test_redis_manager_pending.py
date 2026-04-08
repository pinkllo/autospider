from __future__ import annotations

import pytest

from autospider.common.storage.redis_manager import RedisQueueManager


class _FakePendingClient:
    def __init__(self, *, pending_result, total_items: int = 0, stream_length: int = 0) -> None:
        self.pending_result = pending_result
        self.total_items = total_items
        self.stream_length = stream_length

    async def xpending(self, stream_key: str, group_name: str):
        return self.pending_result

    async def hlen(self, data_key: str) -> int:
        return self.total_items

    async def xlen(self, stream_key: str) -> int:
        return self.stream_length


@pytest.mark.asyncio
async def test_get_pending_count_supports_dict_xpending_summary():
    manager = RedisQueueManager(key_prefix="test:pending-dict")
    manager.client = _FakePendingClient(
        pending_result={
            "pending": 5,
            "min": "1-0",
            "max": "5-0",
            "consumers": [
                {"name": "worker-a", "pending": 2},
                {"name": "worker-b", "pending": 3},
            ],
        }
    )

    pending_count = await manager.get_pending_count("worker-a")

    assert pending_count == 2


@pytest.mark.asyncio
async def test_get_stats_supports_legacy_list_xpending_summary():
    manager = RedisQueueManager(key_prefix="test:pending-list")
    manager.client = _FakePendingClient(
        pending_result=[5, "1-0", "5-0", [["worker-a", 2], ["worker-b", 3]]],
        total_items=12,
        stream_length=7,
    )

    stats = await manager.get_stats()

    assert stats["total_items"] == 12
    assert stats["stream_length"] == 7
    assert stats["pending_count"] == 5
    assert stats["consumers"] == [
        {"name": "worker-a", "pending": 2},
        {"name": "worker-b", "pending": 3},
    ]

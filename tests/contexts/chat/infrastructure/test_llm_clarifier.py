from __future__ import annotations

import pytest

from autospider.contexts.chat.domain.model import DialogueMessage
from autospider.contexts.chat.infrastructure.adapters.llm_clarifier import (
    TaskClarifierAdapter,
)


class StubPlatformClarifier:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    async def clarify(self, history: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"history": history, **kwargs})
        return dict(self.payload)


def _history() -> list[DialogueMessage]:
    return [DialogueMessage(role="user", content="抓取商品标题和价格")]


@pytest.mark.asyncio
async def test_task_clarifier_adapter_maps_ready_payload_to_domain_task() -> None:
    clarifier = StubPlatformClarifier(
        {
            "status": "ready",
            "intent": "collect products",
            "confidence": 0.9,
            "list_url": "https://example.com/list",
            "task_description": "collect product cards",
            "fields": [
                {
                    "name": "title",
                    "description": "product title",
                    "required": True,
                    "data_type": "text",
                }
            ],
            "group_by": "category",
            "requested_categories": ["electronics"],
            "target_url_count": "12",
        }
    )

    result = await TaskClarifierAdapter(clarifier).clarify(_history())

    assert result.status == "ready"
    assert result.task is not None
    assert result.task.list_url == "https://example.com/list"
    assert result.task.fields[0].name == "title"
    assert result.task.group_by == "category"
    assert result.task.requested_categories == ("electronics",)
    assert result.task.target_url_count == 12
    assert clarifier.calls[0]["history"] == [{"role": "user", "content": "抓取商品标题和价格"}]


@pytest.mark.asyncio
async def test_task_clarifier_adapter_converts_incomplete_ready_payload_to_clarification() -> None:
    clarifier = StubPlatformClarifier(
        {
            "status": "ready",
            "intent": "collect products",
            "confidence": 0.8,
            "list_url": "https://example.com/list",
            "task_description": "collect product cards",
            "fields": [],
        }
    )

    result = await TaskClarifierAdapter(clarifier).clarify(_history())

    assert result.status == "need_clarification"
    assert result.task is None
    assert "列表页 URL" in result.next_question


@pytest.mark.asyncio
async def test_task_clarifier_adapter_converts_soft_reject_to_fallback_question() -> None:
    clarifier = StubPlatformClarifier(
        {
            "status": "reject",
            "intent": "collect products",
            "confidence": 0.3,
            "rejection_reason": "缺少 URL，信息不足",
        }
    )

    result = await TaskClarifierAdapter(clarifier).clarify(_history())

    assert result.status == "need_clarification"
    assert result.reason == ""
    assert "A. 直接提供目标站的列表页 URL" in result.next_question

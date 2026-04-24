from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.platform.browser.som.text_first import disambiguate_mark_id_by_text
from autospider.platform.browser.visual_decision_cache import VisualDecisionCache


def test_visual_cache_does_not_hit_across_page_state_signature() -> None:
    cache = VisualDecisionCache()
    cache.put_success(
        page_state_signature="sig-a",
        purpose="mark_text",
        target_text="下一页",
        candidate_text="下一页",
        confidence=1.0,
    )

    assert cache.get(page_state_signature="sig-b", purpose="mark_text", target_text="下一页") == {}


@pytest.mark.asyncio
async def test_text_first_cache_hit_uses_existing_candidate_without_llm() -> None:
    cache = VisualDecisionCache()
    cache.put_success(
        page_state_signature="sig-a",
        purpose="mark_text",
        target_text="下一页",
        candidate_text="下一页",
        confidence=1.0,
    )
    candidates = [SimpleNamespace(mark_id=7, text="下一页", bbox=SimpleNamespace(model_dump=lambda: {}))]

    resolved = await disambiguate_mark_id_by_text(
        page=SimpleNamespace(),
        llm=SimpleNamespace(),
        candidates=candidates,
        target_text="下一页",
        visual_cache=cache,
        page_state_signature="sig-a",
    )

    assert resolved == 7


@pytest.mark.asyncio
async def test_text_first_cache_miss_on_missing_dom_returns_none_and_records_reject() -> None:
    cache = VisualDecisionCache()
    cache.put_success(
        page_state_signature="sig-a",
        purpose="mark_text",
        target_text="下一页",
        candidate_text="旧文本",
        confidence=1.0,
    )

    resolved = await disambiguate_mark_id_by_text(
        page=SimpleNamespace(),
        llm=SimpleNamespace(),
        candidates=[],
        target_text="下一页",
        visual_cache=cache,
        page_state_signature="sig-a",
    )

    assert resolved is None
    assert cache.get(page_state_signature="sig-a", purpose="mark_text", target_text="下一页")["status"] == "rejected"

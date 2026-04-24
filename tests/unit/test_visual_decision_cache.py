from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.platform.browser.som.text_first import disambiguate_mark_id_by_text
from autospider.platform.browser.visual_decision_cache import VisualDecisionCache

NEXT_TEXT = "\u4e0b\u4e00\u9875"
OLD_TEXT = "\u65e7\u6587\u6848"


def test_visual_cache_hits_across_page_state_signature_when_semantics_match() -> None:
    cache = VisualDecisionCache()
    cache.put_success(
        page_state_signature="sig-a",
        purpose="mark_text",
        target_text=NEXT_TEXT,
        candidate_text=NEXT_TEXT,
        confidence=1.0,
    )

    cached = cache.get(page_state_signature="sig-b", purpose="mark_text", target_text=NEXT_TEXT)

    assert cached["status"] == "success"
    assert cached["page_state_signature"] == "sig-a"


@pytest.mark.asyncio
async def test_text_first_cache_hit_uses_existing_candidate_without_llm() -> None:
    cache = VisualDecisionCache()
    cache.put_success(
        page_state_signature="sig-a",
        purpose="mark_text",
        target_text=NEXT_TEXT,
        candidate_text=NEXT_TEXT,
        confidence=1.0,
    )
    candidates = [SimpleNamespace(mark_id=7, text=NEXT_TEXT, bbox=SimpleNamespace(model_dump=lambda: {}))]

    resolved = await disambiguate_mark_id_by_text(
        page=SimpleNamespace(),
        llm=SimpleNamespace(),
        candidates=candidates,
        target_text=NEXT_TEXT,
        visual_cache=cache,
        page_state_signature="sig-b",
    )

    assert resolved == 7


@pytest.mark.asyncio
async def test_text_first_cache_miss_on_missing_dom_returns_none_and_records_reject() -> None:
    cache = VisualDecisionCache()
    cache.put_success(
        page_state_signature="sig-a",
        purpose="mark_text",
        target_text=NEXT_TEXT,
        candidate_text=OLD_TEXT,
        confidence=1.0,
    )

    resolved = await disambiguate_mark_id_by_text(
        page=SimpleNamespace(),
        llm=SimpleNamespace(),
        candidates=[],
        target_text=NEXT_TEXT,
        visual_cache=cache,
        page_state_signature="sig-b",
    )

    assert resolved is None
    assert cache.get(page_state_signature="sig-b", purpose="mark_text", target_text=NEXT_TEXT)["status"] == "rejected"
    assert cache.get(page_state_signature="sig-a", purpose="mark_text", target_text=NEXT_TEXT)["status"] == "success"


def test_visual_cache_reject_does_not_poison_other_page_states() -> None:
    cache = VisualDecisionCache()
    cache.put_success(
        page_state_signature="sig-a",
        purpose="mark_text",
        target_text=NEXT_TEXT,
        candidate_text=NEXT_TEXT,
        confidence=1.0,
    )

    cache.put_reject(
        page_state_signature="sig-b",
        purpose="mark_text",
        target_text=NEXT_TEXT,
        reason="missing_dom_candidate",
    )

    assert cache.get(page_state_signature="sig-b", purpose="mark_text", target_text=NEXT_TEXT)["status"] == "rejected"
    assert cache.get(page_state_signature="sig-a", purpose="mark_text", target_text=NEXT_TEXT)["status"] == "success"

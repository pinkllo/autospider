from __future__ import annotations

from autospider.contexts.collection.application.use_cases.paginate import (
    _is_continuation_purpose,
    _pagination_rule_selectors,
)


def test_pagination_rule_selectors_include_load_more_controls() -> None:
    selectors = _pagination_rule_selectors()

    assert 'button:has-text("Load More")' in selectors
    assert 'button:has-text("加载更多")' in selectors
    assert ".load-more-btn:not([disabled])" in selectors


def test_continuation_purpose_accepts_load_more_aliases() -> None:
    assert _is_continuation_purpose("pagination_next") is True
    assert _is_continuation_purpose("pagination_continue") is True
    assert _is_continuation_purpose("load_more") is True
    assert _is_continuation_purpose("detail_links") is False

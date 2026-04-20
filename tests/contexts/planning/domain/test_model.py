from __future__ import annotations

from autospider.contexts.planning.domain.model import (
    ExecutionBrief,
    PlannerIntent,
    format_execution_brief,
)


def test_planner_intent_normalizes_none_grouping() -> None:
    intent = PlannerIntent.from_payload(
        {
            "group_by": "invalid",
            "per_group_target_count": 0,
            "total_target_count": "5",
            "category_discovery_mode": "manual",
            "requested_categories": ["A"],
        }
    )

    assert intent.group_by == "none"
    assert intent.per_group_target_count is None
    assert intent.total_target_count == 5
    assert intent.requested_categories == []


def test_format_execution_brief_renders_structured_text() -> None:
    text = format_execution_brief(
        ExecutionBrief(
            parent_chain=["首页", "公告"],
            current_scope="招标公告",
            objective="抓取标题",
            do_not=["不要翻回首页"],
        )
    )

    assert "首页 > 公告" in text
    assert "当前作用域: 招标公告" in text
    assert "禁止: 不要翻回首页" in text

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from autospider.crawler.planner.task_planner import TaskPlanner


async def _return_none(*args, **kwargs):
    return None


async def _return_navigation_tuple(*args, **kwargs):
    return "", []


def test_extract_subtask_urls_skips_unresolved_candidates():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner.page = SimpleNamespace(url="https://example.com/home")
    planner._resolve_mark_id_from_link_text = _return_none
    planner._get_href_by_js = _return_none
    planner._get_url_by_navigation = _return_navigation_tuple

    subtasks = asyncio.run(
        planner._extract_subtask_urls(
            {
                "subtasks": [
                    {
                        "name": "新闻公告",
                        "link_text": "新闻公告",
                        "task_description": "采集新闻公告列表",
                    }
                ]
            },
            SimpleNamespace(marks=[]),
        )
    )

    assert subtasks == []


def test_page_state_signature_distinguishes_same_url_different_nav_steps():
    planner = TaskPlanner.__new__(TaskPlanner)

    sig_a = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "招标公告", "thinking": "first"}],
    )
    sig_b = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "中标公告", "thinking": "second"}],
    )

    assert sig_a != sig_b


def test_page_state_signature_ignores_unstable_nav_fields():
    planner = TaskPlanner.__new__(TaskPlanner)

    sig_a = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "公告", "thinking": "alpha", "success": True}],
    )
    sig_b = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "公告", "thinking": "beta", "success": False}],
    )

    assert sig_a == sig_b

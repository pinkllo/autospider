from __future__ import annotations

import asyncio
from types import SimpleNamespace

from autospider.crawler.planner.task_planner import TaskPlanner


async def _return_none(*args, **kwargs):
    return None


def test_extract_subtask_urls_skips_unresolved_candidates():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner.page = SimpleNamespace(url="https://example.com/home")
    planner._resolve_mark_id_from_link_text = _return_none
    planner._get_href_by_js = _return_none
    planner._get_url_by_navigation = _return_none

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

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.common.types import Action, ActionType
from autospider.crawler.collector.navigation_handler import NavigationHandler


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/list"

    async def title(self) -> str:
        return "采购公告"


class _FakeDecider:
    def __init__(self) -> None:
        self.task_plan: str | None = None

    async def decide(self, *_args, **_kwargs):
        return Action(action=ActionType.DONE, thinking="筛选完成")


@pytest.mark.asyncio
async def test_navigation_phase_task_plan_includes_decision_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_clear_overlay(_page) -> None:
        return None

    async def fake_inject_and_scan(_page):
        return SimpleNamespace(
            marks=[],
            scroll_info=None,
        )

    async def fake_capture_screenshot_with_marks(_page):
        return b"", "base64-image"

    monkeypatch.setattr(
        "autospider.crawler.collector.navigation_handler.clear_overlay",
        fake_clear_overlay,
    )
    monkeypatch.setattr(
        "autospider.crawler.collector.navigation_handler.inject_and_scan",
        fake_inject_and_scan,
    )
    monkeypatch.setattr(
        "autospider.crawler.collector.navigation_handler.capture_screenshot_with_marks",
        fake_capture_screenshot_with_marks,
    )
    monkeypatch.setattr(
        "autospider.crawler.collector.navigation_handler.build_mark_id_to_xpath_map",
        lambda _snapshot: {},
    )

    decider = _FakeDecider()
    handler = NavigationHandler(
        page=_FakePage(),
        list_url="https://example.com/list",
        task_description="筛选最近 30 天的采购公告",
        max_nav_steps=1,
        execution_brief={"objective": "收集采购公告详情页"},
        decider=decider,
    )
    handler.decision_context = {
        "page_model": {
            "page_type": "stateful_list",
            "metadata": {"observations": "该列表页支持按公告类型和日期联合筛选"},
        },
        "recent_failures": [
            {
                "page_id": "node_002",
                "category": "navigation",
                "detail": "上一次误入政策解读页",
            }
        ],
        "current_plan": {
            "goal": "优先进入采购公告筛选结果",
            "page_id": "node_002",
            "stage": "planning_seeded",
        },
    }

    assert await handler.run_navigation_phase() is True
    assert decider.task_plan is not None
    assert "优先进入采购公告筛选结果" in decider.task_plan
    assert "该列表页支持按公告类型和日期联合筛选" in decider.task_plan
    assert "上一次误入政策解读页" in decider.task_plan

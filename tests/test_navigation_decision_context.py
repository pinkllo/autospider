from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.legacy.common.types import Action, ActionType
from autospider.legacy.crawler.collector.navigation_handler import NavigationHandler
from autospider.contexts.planning.domain import classify_protocol_violation


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


class _ContractViolationDecider:
    def __init__(self) -> None:
        self.task_plan: str | None = None

    async def decide(self, *_args, **_kwargs):
        return Action(
            action=ActionType.RETRY,
            thinking="contract_violation",
            failure_record=classify_protocol_violation(
                component="decider",
                diagnostics={
                    "action": "click",
                    "validation_errors": ["click requires target_text or mark_id"],
                },
            ),
        )


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
        "autospider.legacy.crawler.collector.navigation_handler.clear_overlay",
        fake_clear_overlay,
    )
    monkeypatch.setattr(
        "autospider.legacy.crawler.collector.navigation_handler.inject_and_scan",
        fake_inject_and_scan,
    )
    monkeypatch.setattr(
        "autospider.legacy.crawler.collector.navigation_handler.capture_screenshot_with_marks",
        fake_capture_screenshot_with_marks,
    )
    monkeypatch.setattr(
        "autospider.legacy.crawler.collector.navigation_handler.build_mark_id_to_xpath_map",
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
    }

    assert await handler.run_navigation_phase() is True
    assert decider.task_plan is not None
    assert "该列表页支持按公告类型和日期联合筛选" in decider.task_plan
    assert "上一次误入政策解读页" in decider.task_plan


@pytest.mark.asyncio
async def test_navigation_phase_stops_on_decider_contract_violation(
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
        "autospider.legacy.crawler.collector.navigation_handler.clear_overlay",
        fake_clear_overlay,
    )
    monkeypatch.setattr(
        "autospider.legacy.crawler.collector.navigation_handler.inject_and_scan",
        fake_inject_and_scan,
    )
    monkeypatch.setattr(
        "autospider.legacy.crawler.collector.navigation_handler.capture_screenshot_with_marks",
        fake_capture_screenshot_with_marks,
    )
    monkeypatch.setattr(
        "autospider.legacy.crawler.collector.navigation_handler.build_mark_id_to_xpath_map",
        lambda _snapshot: {},
    )

    decider = _ContractViolationDecider()
    handler = NavigationHandler(
        page=_FakePage(),
        list_url="https://example.com/list",
        task_description="筛选最近 30 天的采购公告",
        max_nav_steps=1,
        execution_brief={"objective": "收集采购公告详情页"},
        decider=decider,
    )

    assert await handler.run_navigation_phase() is False
    assert handler.nav_steps[0]["action"] == "retry"
    assert handler.nav_steps[0]["success"] is False
    assert handler.nav_steps[0]["failure_record"]["category"] == "contract_violation"
    assert handler.nav_steps[0]["recovery_directive"]["action"] == "reask"

from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.contexts.planning.domain.page_state import PlannerPageState


class _FakeCandidate:
    def __init__(self, xpath: str) -> None:
        self.xpath = xpath
        self.priority = 1
        self.strategy = "attr"


class _FakeMark:
    def __init__(self) -> None:
        self.mark_id = 7
        self.text = "成交结果"
        self.tag = "button"
        self.href = ""
        self.role = "tab"
        self.xpath_candidates = [_FakeCandidate("//button[@data-tab='results']")]


class _FakePage:
    def __init__(self) -> None:
        self.goto_calls: list[str] = []

    async def goto(
        self, url: str, wait_until: str = "domcontentloaded", timeout: int = 15000
    ) -> None:
        del wait_until
        del timeout
        self.goto_calls.append(url)

    async def wait_for_timeout(self, timeout: int) -> None:
        del timeout


def test_build_nav_click_step_marks_same_page_validation_for_tab_like_elements() -> None:
    state = PlannerPageState(page=None)
    snapshot = SimpleNamespace(marks=[_FakeMark()])

    step = state.build_nav_click_step(snapshot, 7)

    assert step is not None
    assert step["state_validation"] == {
        "kind": "same_page_activation",
        "interaction_xpath": "//button[@data-tab='results']",
    }


@pytest.mark.asyncio
async def test_restore_page_state_rejects_successful_but_unvalidated_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    state = PlannerPageState(page=page)

    class _FakeNavigationHandler:
        def __init__(self, page, list_url: str, task_description: str, max_nav_steps: int) -> None:
            del page
            del list_url
            del task_description
            del max_nav_steps

        async def replay_nav_steps(self, nav_steps: list[dict[str, object]]):
            assert nav_steps[0]["state_validation"]["kind"] == "same_page_activation"
            return SimpleNamespace(
                success=True,
                failure_reason="",
                validation_status="skipped",
                required_validation_steps=1,
                validated_steps=0,
            )

    monkeypatch.setattr(
        "autospider.legacy.crawler.collector.navigation_handler.NavigationHandler",
        _FakeNavigationHandler,
    )

    restored = await state.restore_page_state(
        "https://example.com/list",
        [
            {
                "action": "click",
                "success": True,
                "clicked_element_xpath_candidates": [
                    {"xpath": "//button[@data-tab='results']", "priority": 1, "strategy": "attr"}
                ],
                "state_validation": {
                    "kind": "same_page_activation",
                    "interaction_xpath": "//button[@data-tab='results']",
                },
            }
        ],
    )

    assert restored is False

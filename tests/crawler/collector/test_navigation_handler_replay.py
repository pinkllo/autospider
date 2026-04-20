from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.contexts.collection.infrastructure.crawler.collector.navigation_handler import NavigationHandler


class _FakeLocator:
    def __init__(self, page: "_FakePage") -> None:
        self._page = page
        self.first = self

    async def count(self) -> int:
        return 1

    async def inner_text(self, timeout: int = 1000) -> str:
        del timeout
        return "成交结果"

    async def click(self, timeout: int = 5000) -> None:
        del timeout
        self._page.state["aria_selected"] = "true"

    async def fill(self, text: str, timeout: int = 5000) -> None:
        del text
        del timeout

    async def press(self, key: str, timeout: int = 5000) -> None:
        del key
        del timeout


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/list"
        self.state = {
            "class_name": "",
            "aria_selected": "false",
            "aria_current": "",
            "data_state": "",
        }
        self.mouse = SimpleNamespace(wheel=self._wheel)
        self.keyboard = SimpleNamespace(press=self._press)

    def locator(self, query: str) -> _FakeLocator:
        assert query.startswith("xpath=")
        return _FakeLocator(self)

    def get_by_text(self, text: str, exact: bool = False) -> _FakeLocator:
        del text
        del exact
        return _FakeLocator(self)

    async def evaluate(self, script: str, xpath: str) -> dict[str, str]:
        del script
        assert xpath == "//button[@data-tab='results']"
        return dict(self.state)

    async def wait_for_load_state(self, state: str, timeout: int = 0) -> None:
        del state
        del timeout

    async def wait_for_timeout(self, timeout: int) -> None:
        del timeout

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        del wait_until
        del timeout

    async def _wheel(self, delta_x: int, delta_y: int) -> None:
        del delta_x
        del delta_y

    async def _press(self, key: str) -> None:
        del key


def _same_page_step() -> dict[str, object]:
    return {
        "action": "click",
        "success": True,
        "target_text": "成交结果",
        "clicked_element_text": "成交结果",
        "clicked_element_xpath_candidates": [
            {
                "xpath": "//button[@data-tab='results']",
                "priority": 1,
                "strategy": "attr",
            }
        ],
        "state_validation": {
            "kind": "same_page_activation",
            "interaction_xpath": "//button[@data-tab='results']",
        },
    }


@pytest.mark.asyncio
async def test_replay_nav_steps_returns_explicit_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    handler = NavigationHandler(page=page, list_url=page.url, task_description="", max_nav_steps=3)

    async def _no_state_change(**kwargs):
        del kwargs
        return None

    monkeypatch.setattr(
        "autospider.contexts.collection.infrastructure.crawler.collector.navigation_handler.click_and_capture_new_page",
        _no_state_change,
    )

    result = await handler.replay_nav_steps([_same_page_step()])

    assert result.success is False
    assert result.failure_reason == "same_page_state_not_activated"
    assert result.validation_status == "failed"
    assert result.failed_step == 1


@pytest.mark.asyncio
async def test_replay_nav_steps_returns_passed_validation_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    handler = NavigationHandler(page=page, list_url=page.url, task_description="", max_nav_steps=3)

    async def _activate_state(**kwargs):
        page.state["aria_selected"] = "true"
        del kwargs
        return None

    monkeypatch.setattr(
        "autospider.contexts.collection.infrastructure.crawler.collector.navigation_handler.click_and_capture_new_page",
        _activate_state,
    )

    result = await handler.replay_nav_steps([_same_page_step()])

    assert result.success is True
    assert result.validation_status == "passed"
    assert result.required_validation_steps == 1
    assert result.validated_steps == 1

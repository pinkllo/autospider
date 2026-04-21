from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.contexts.collection.application.use_cases.extract_urls import URLExtractor


class _FakeLocator:
    async def count(self) -> int:
        return 1

    async def get_attribute(self, name: str):
        del name
        return None

    def locator(self, query: str) -> "_FakeLocator":
        del query
        return self


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/list"
        self.goto_calls: list[str] = []

    async def goto(
        self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000
    ) -> None:
        del wait_until
        del timeout
        self.url = url
        self.goto_calls.append(url)

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 5000) -> None:
        del wait_until
        del timeout


@pytest.mark.asyncio
async def test_click_element_and_get_url_raises_when_restore_replay_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    extractor = URLExtractor(page=page, list_url="https://example.com/list")

    async def _change_url(**kwargs):
        del kwargs
        page.url = "https://example.com/detail/1"
        return None

    class _FakeNavigationHandler:
        def __init__(self, page, list_url: str, task_description: str, max_nav_steps: int) -> None:
            del page
            del list_url
            del task_description
            del max_nav_steps

        async def replay_nav_steps(self, nav_steps: list[dict[str, object]]):
            assert nav_steps == [{"action": "click"}]
            return SimpleNamespace(
                success=False,
                failure_reason="same_page_state_not_activated",
                validation_status="failed",
                required_validation_steps=1,
                validated_steps=0,
            )

    monkeypatch.setattr(
        "autospider.contexts.collection.application.use_cases.extract_urls.click_and_capture_new_page",
        _change_url,
    )
    monkeypatch.setattr(
        "autospider.contexts.collection.application.use_cases.navigate.NavigationHandler",
        _FakeNavigationHandler,
    )
    monkeypatch.setattr(
        "autospider.contexts.collection.application.use_cases.extract_urls.asyncio.sleep",
        lambda *_args, **_kwargs: _completed_awaitable(),
    )

    with pytest.raises(RuntimeError, match="detail_page_restore_replay_failed"):
        await extractor.click_element_and_get_url(_FakeLocator(), nav_steps=[{"action": "click"}])


async def _completed_awaitable() -> None:
    return None

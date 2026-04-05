from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.common.types import ActionResult
from autospider.crawler.collector.url_extractor import URLExtractor


class _FakeLocator:
    def __init__(self, *, href: str | None = None, nested_href: str | None = None, visible: bool = True):
        self._href = href
        self._nested_href = nested_href
        self._visible = visible
        self.first = self

    async def get_attribute(self, name: str):
        if name != "href":
            return None
        return self._href

    def locator(self, query: str):
        if query == "xpath=.//a[@href]" and self._nested_href:
            return _FakeLocator(href=self._nested_href)
        return _FakeLocator(visible=False)

    async def count(self):
        return 1 if self._visible else 0

    async def is_visible(self):
        return self._visible


class _FakePage:
    def __init__(self, locator_obj: _FakeLocator):
        self._locator = locator_obj
        self.url = "https://example.com/list"

    def locator(self, query: str):
        if query.startswith("xpath="):
            return self._locator
        raise AssertionError(f"unexpected query: {query}")

    def get_by_text(self, text: str, exact: bool = False):
        raise AssertionError(f"unexpected get_by_text: {text}, exact={exact}")


@pytest.mark.asyncio
async def test_extract_from_locator_reads_descendant_anchor_href():
    extractor = URLExtractor(page=SimpleNamespace(), list_url="https://example.com/list")
    locator = _FakeLocator(href=None, nested_href="/detail/1")

    url = await extractor.extract_from_locator(locator)

    assert url == "https://example.com/detail/1"


@pytest.mark.asyncio
async def test_extract_from_element_prefers_xpath_locator_before_click_fallback():
    page = _FakePage(_FakeLocator(href=None, nested_href="/detail/2"))
    extractor = URLExtractor(page=page, list_url="https://example.com/list")
    element = SimpleNamespace(
        href=None,
        text="公告标题",
        xpath_candidates=[SimpleNamespace(xpath="//section/ul/li[1]")],
    )

    async def _unexpected_click(*args, **kwargs):
        raise AssertionError("should not fall back to click_and_get_url")

    extractor.click_and_get_url = _unexpected_click
    url = await extractor.extract_from_element(element, snapshot=SimpleNamespace())

    assert url == "https://example.com/detail/2"


@pytest.mark.asyncio
async def test_click_and_get_url_falls_back_to_locator_click_when_mark_id_click_fails(monkeypatch):
    page = _FakePage(_FakeLocator(href=None, nested_href=None))
    extractor = URLExtractor(page=page, list_url="https://example.com/list")
    element = SimpleNamespace(
        mark_id=999,
        href=None,
        text="公告标题",
        xpath_candidates=[SimpleNamespace(xpath="//section/ul/li[1]")],
    )

    class _FakeExecutor:
        def __init__(self, page):
            self.page = page

        async def execute(self, action, mark_id_to_xpath, step_index):
            return ActionResult(success=False, error="点击动作缺少 mark_id 或 target_text"), None

    async def _fake_click_element_and_get_url(locator, nav_steps=None):
        return "https://example.com/detail/3"

    async def _fake_set_overlay_visibility(page, visible):
        return None

    monkeypatch.setattr(
        "autospider.crawler.collector.url_extractor.ActionExecutor",
        _FakeExecutor,
    )
    monkeypatch.setattr(
        "autospider.crawler.collector.url_extractor.set_overlay_visibility",
        _fake_set_overlay_visibility,
    )
    monkeypatch.setattr(
        "autospider.crawler.collector.url_extractor.build_mark_id_to_xpath_map",
        lambda snapshot: {},
    )
    extractor.click_element_and_get_url = _fake_click_element_and_get_url

    url = await extractor.click_and_get_url(element, snapshot=SimpleNamespace(), nav_steps=[])

    assert url == "https://example.com/detail/3"

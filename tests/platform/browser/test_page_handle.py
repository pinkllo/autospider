from __future__ import annotations

import asyncio

import pytest

from autospider.platform.browser import page_handle
from autospider.platform.browser.guarded_page import GuardedPage
from autospider.platform.browser.page_handle import coerce_context_pages, resolve_previous_page, unwrap_page


class _FakeContext:
    def __init__(self) -> None:
        self.pages: list[_FakePage] = []


class _FakePage:
    def __init__(self, name: str, context: _FakeContext) -> None:
        self.name = name
        self.url = f"https://example.com/{name}"
        self.context = context
        self.main_frame = object()
        self._closed = False
        self._opener = None
        self._events: dict[str, list[object]] = {}

    def on(self, event: str, handler: object) -> None:
        self._events.setdefault(event, []).append(handler)

    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True

    async def wait_for_load_state(self, *_args, **_kwargs) -> None:
        return None

    def opener(self):
        return self._opener


class _FakeGuard:
    def __init__(self) -> None:
        self.attached: list[str] = []
        self.inspected: list[str] = []

    def attach_to_page(self, page: _FakePage) -> None:
        page._page_guard = self
        page._guard_attached = True
        self.attached.append(page.name)

    async def run_inspection(self, page: _FakePage) -> None:
        self.inspected.append(page.name)

    async def wait_until_idle(self) -> None:
        return None


@pytest.mark.asyncio
async def test_coerce_context_pages_wraps_raw_context_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[asyncio.Task] = []

    def _create_task(coro, task_name: str):
        del task_name
        task = asyncio.create_task(coro)
        scheduled.append(task)
        return task

    monkeypatch.setattr(page_handle, "create_monitored_task", _create_task)

    context = _FakeContext()
    current = _FakePage("current", context)
    sibling = _FakePage("sibling", context)
    context.pages = [current, sibling]

    guard = _FakeGuard()
    guard.attach_to_page(current)
    guarded_current = GuardedPage(current, guard)

    pages = coerce_context_pages(guarded_current)
    await asyncio.gather(*scheduled)

    assert len(pages) == 2
    assert all(isinstance(page, GuardedPage) for page in pages)
    assert unwrap_page(pages[0]) is current
    assert unwrap_page(pages[1]) is sibling
    assert sibling._page_guard is guard
    assert "sibling" in guard.inspected


@pytest.mark.asyncio
async def test_resolve_previous_page_wraps_raw_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[asyncio.Task] = []

    def _create_task(coro, task_name: str):
        del task_name
        task = asyncio.create_task(coro)
        scheduled.append(task)
        return task

    monkeypatch.setattr(page_handle, "create_monitored_task", _create_task)

    context = _FakeContext()
    parent = _FakePage("parent", context)
    current = _FakePage("current", context)
    current._opener = parent
    context.pages = [parent, current]

    guard = _FakeGuard()
    guard.attach_to_page(current)
    guarded_current = GuardedPage(current, guard)

    previous_page = await resolve_previous_page(guarded_current)
    await asyncio.gather(*scheduled)

    assert isinstance(previous_page, GuardedPage)
    assert unwrap_page(previous_page) is parent
    assert parent._page_guard is guard
    assert "parent" in guard.inspected

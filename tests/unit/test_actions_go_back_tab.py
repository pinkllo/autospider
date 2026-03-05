import asyncio

from autospider.common.browser.actions import ActionExecutor


class _FakeRawContext:
    def __init__(self):
        self.pages = []


class _FakeRawPage:
    def __init__(self, url: str, context: _FakeRawContext):
        self.url = url
        self.context = context
        self._closed = False
        self._opener_page = None

    async def opener(self):
        return self._opener_page

    def is_closed(self) -> bool:
        return self._closed


class _FakeGuardedContext:
    def __init__(self):
        self.pages = []


class _FakeGuardedPage:
    def __init__(self, raw_page: _FakeRawPage, guarded_context: _FakeGuardedContext):
        self._raw_page = raw_page
        self.context = guarded_context

    @property
    def url(self) -> str:
        return self._raw_page.url

    def unwrap(self) -> _FakeRawPage:
        return self._raw_page

    async def close(self):
        self._raw_page._closed = True


def test_go_back_tab_should_await_opener_and_switch_to_previous_guarded_page():
    raw_context = _FakeRawContext()
    raw_previous = _FakeRawPage("https://example.com/prev", raw_context)
    raw_current = _FakeRawPage("https://example.com/current", raw_context)
    raw_current._opener_page = raw_previous
    raw_context.pages = [raw_previous, raw_current]

    guarded_context = _FakeGuardedContext()
    previous_page = _FakeGuardedPage(raw_previous, guarded_context)
    current_page = _FakeGuardedPage(raw_current, guarded_context)
    guarded_context.pages = [previous_page, current_page]

    executor = ActionExecutor(current_page)
    result, _ = asyncio.run(executor._execute_go_back_tab(step_index=1))

    assert result.success is True
    assert result.new_url == "https://example.com/prev"
    assert executor.page is previous_page
    assert raw_current.is_closed() is True

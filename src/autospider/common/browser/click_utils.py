"""Shared click utilities.

Goal: centralize "click + new page detection" so ActionExecutor and collector code
do not re-implement it in multiple places.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeout

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page
    from browser_manager.guarded_page import GuardedPage


async def click_and_capture_new_page(
    *,
    page: "Page | GuardedPage",
    locator: "Locator",
    click_timeout_ms: int = 5000,
    expect_page_timeout_ms: int = 3000,
    load_state: str = "domcontentloaded",
    load_timeout_ms: int = 10000,
) -> "Page | GuardedPage | None":
    """Click a locator and capture a newly opened page if any.

    Notes:
    - Prefer context.expect_page to listen for new page events.
    - If expect_page times out but the number of pages increases, fall back to the
      last page as a best-effort delayed-open detection.
    - This helper only returns the new Page; it does not switch or close pages.
    """
    context = page.context
    pages_before = len(context.pages)

    new_page: "Page | None" = None
    try:
        async with context.expect_page(timeout=expect_page_timeout_ms) as new_page_info:
            await locator.click(timeout=click_timeout_ms)
        new_page = await new_page_info.value
    except PlaywrightTimeout:
        pass

    if new_page is None and len(context.pages) > pages_before:
        new_page = context.pages[-1]

    if new_page is not None:
        try:
            await new_page.wait_for_load_state(load_state, timeout=load_timeout_ms)
        except Exception:
            pass

    if new_page is not None:
        new_page = _ensure_guarded_page(new_page)

    return new_page


def _ensure_guarded_page(page: "Page | GuardedPage") -> "Page | GuardedPage":
    try:
        import browser_manager.handlers as _handlers  # noqa: F401
        from browser_manager.guard import PageGuard
        from browser_manager.guarded_page import GuardedPage
    except Exception:
        return page

    if isinstance(page, GuardedPage):
        return page

    guard = getattr(page, "_page_guard", None)
    if guard is None:
        guard = PageGuard()
        guard.attach_to_page(page)
        setattr(page, "_guard_attached", True)
        setattr(page, "_page_guard", guard)
    return GuardedPage(page, guard)

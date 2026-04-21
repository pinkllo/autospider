"""Browser page helpers for guarded/raw page interop."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .task_utils import create_monitored_task

if TYPE_CHECKING:
    from .guard import PageGuard


def _is_guarded_page(page: Any) -> bool:
    from .guarded_page import GuardedPage

    return isinstance(page, GuardedPage)


def _looks_like_page(page: Any) -> bool:
    return all(hasattr(page, name) for name in ("context", "is_closed", "on", "main_frame"))


def unwrap_page(page: Any) -> Any:
    if _is_guarded_page(page):
        return page.unwrap()
    return page


def get_page_guard(page: Any) -> "PageGuard | None":
    raw_page = unwrap_page(page)
    guard = getattr(raw_page, "_page_guard", None)
    if guard is not None:
        return guard
    if _is_guarded_page(page):
        return object.__getattribute__(page, "_guard")
    return None


def wrap_page_with_guard(page: Any, guard: "PageGuard | None") -> Any:
    if guard is None or not _looks_like_page(page):
        return page
    if _is_guarded_page(page):
        return page

    if not getattr(page, "_guard_attached", False):
        guard.attach_to_page(page)
        create_monitored_task(
            guard.run_inspection(page),
            task_name="PageHandle.wrap_page_inspection",
        )

    from .guarded_page import GuardedPage

    return GuardedPage(page, guard)


def coerce_guarded_page(page: Any, reference: Any) -> Any:
    if _is_guarded_page(page):
        return page
    return wrap_page_with_guard(page, get_page_guard(reference))


def coerce_context_pages(page: Any) -> list[Any]:
    raw_page = unwrap_page(page)
    context = getattr(raw_page, "context", None)
    pages = getattr(context, "pages", None)
    if pages is None:
        return []

    guard = get_page_guard(page)
    return [wrap_page_with_guard(candidate, guard) for candidate in list(pages)]


def pages_match(left: Any, right: Any) -> bool:
    return unwrap_page(left) is unwrap_page(right)


async def resolve_previous_page(current_page: Any, previous_page: Any = None) -> Any | None:
    raw_current = unwrap_page(current_page)
    target_page = previous_page
    if asyncio.iscoroutine(target_page):
        target_page = await target_page

    if target_page is None:
        try:
            opener = getattr(raw_current, "opener", None)
            if callable(opener):
                opener_result = opener()
                if asyncio.iscoroutine(opener_result):
                    opener_result = await opener_result
                target_page = opener_result
        except Exception:
            target_page = None

    if asyncio.iscoroutine(target_page):
        target_page = await target_page

    if target_page is None:
        for candidate in reversed(coerce_context_pages(current_page)):
            if pages_match(candidate, current_page):
                continue
            target_page = candidate
            break

    if target_page is None:
        return None
    return coerce_guarded_page(target_page, current_page)


def is_page_closed(page: Any) -> bool:
    try:
        closed = getattr(unwrap_page(page), "is_closed")
        return bool(closed() if callable(closed) else closed)
    except Exception:
        return False


__all__ = [
    "coerce_context_pages",
    "coerce_guarded_page",
    "get_page_guard",
    "is_page_closed",
    "pages_match",
    "resolve_previous_page",
    "unwrap_page",
    "wrap_page_with_guard",
]

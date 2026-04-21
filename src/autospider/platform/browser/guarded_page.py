"""
Page 代理类模块（__getattribute__ 全方法拦截版）。
"""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any, FrozenSet

from playwright.async_api import Page

from .page_handle import wrap_page_with_guard

if TYPE_CHECKING:
    from .guard import PageGuard


class GuardedPage:
    """Page 动态代理类。"""

    _SKIP_WAIT: FrozenSet[str] = frozenset(
        {
            "url",
            "frames",
            "main_frame",
            "is_closed",
            "video",
            "workers",
            "request",
            "viewportSize",
            "unwrap",
            "_page",
            "_guard",
            "_SKIP_WAIT",
            "_LOCATOR_FACTORIES",
            "on",
            "once",
            "remove_listener",
            "set_default_timeout",
            "set_default_navigation_timeout",
        }
    )
    _LOCATOR_FACTORIES: FrozenSet[str] = frozenset(
        {
            "locator",
            "get_by_role",
            "get_by_text",
            "get_by_label",
            "get_by_placeholder",
            "get_by_alt_text",
            "get_by_title",
            "get_by_test_id",
            "frame_locator",
        }
    )

    def __init__(self, page: Page, guard: "PageGuard"):
        object.__setattr__(self, "_page", page)
        object.__setattr__(self, "_guard", guard)

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("_") or name in ("unwrap",):
            return object.__getattribute__(self, name)

        page = object.__getattribute__(self, "_page")
        guard = object.__getattribute__(self, "_guard")
        skip_wait = object.__getattribute__(self, "_SKIP_WAIT")
        locator_factories = object.__getattribute__(self, "_LOCATOR_FACTORIES")

        if name == "context":
            return GuardedContext(page.context, guard)
        if name == "keyboard":
            return GuardedKeyboard(page.keyboard, guard)

        try:
            attr = getattr(page, name)
        except AttributeError as exc:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            ) from exc

        if name in skip_wait:
            return attr

        if name in locator_factories:

            @functools.wraps(attr)
            def locator_factory(*args: Any, **kwargs: Any) -> Any:
                return GuardedLocator(attr(*args, **kwargs), guard)

            return locator_factory

        if asyncio.iscoroutinefunction(attr):

            @functools.wraps(attr)
            async def guarded_wrapper(*args: Any, **kwargs: Any) -> Any:
                await guard.wait_until_idle()
                result = await attr(*args, **kwargs)
                await asyncio.sleep(0.1)
                await guard.wait_until_idle()
                return result

            return guarded_wrapper

        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, "_page"), name, value)

    @property
    def url(self) -> str:
        return object.__getattribute__(self, "_page").url

    @property
    def content(self) -> Any:
        return object.__getattribute__(self, "_page").content

    def is_closed(self) -> bool:
        return object.__getattribute__(self, "_page").is_closed()

    def unwrap(self) -> Page:
        return object.__getattribute__(self, "_page")


class GuardedContext:
    """BrowserContext 代理类。"""

    def __init__(self, context: Any, guard: "PageGuard"):
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_guard", guard)

    def _wrap_page(self, page: Any) -> Any:
        guard = object.__getattribute__(self, "_guard")
        return wrap_page_with_guard(page, guard)

    @property
    def pages(self) -> list["GuardedPage"]:
        context = object.__getattribute__(self, "_context")
        return [self._wrap_page(page) for page in context.pages]

    async def wait_for_event(self, event: str, predicate=None, timeout: float = 30000) -> Any:
        context = object.__getattribute__(self, "_context")
        result = await context.wait_for_event(event, predicate=predicate, timeout=timeout)
        if event == "page":
            await asyncio.sleep(0.1)
            return self._wrap_page(result)
        return result

    async def new_page(self, **kwargs: Any) -> "GuardedPage":
        context = object.__getattribute__(self, "_context")
        page = await context.new_page(**kwargs)
        await asyncio.sleep(0.1)
        return self._wrap_page(page)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_context"), name)


class GuardedKeyboard:
    """Keyboard 代理类。"""

    def __init__(self, keyboard: Any, guard: "PageGuard"):
        object.__setattr__(self, "_keyboard", keyboard)
        object.__setattr__(self, "_guard", guard)

    async def press(self, key: str, **kwargs: Any) -> None:
        keyboard = object.__getattribute__(self, "_keyboard")
        guard = object.__getattribute__(self, "_guard")
        await keyboard.press(key, **kwargs)
        if key.lower() in ("enter", "return"):
            await asyncio.sleep(0.1)
            await guard.wait_until_idle()

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_keyboard"), name)


class GuardedLocator:
    """Locator 代理类。"""

    _CHAIN_METHODS: FrozenSet[str] = frozenset(
        {
            "locator",
            "nth",
            "filter",
            "and_",
            "or_",
            "get_by_role",
            "get_by_text",
            "get_by_label",
            "get_by_placeholder",
            "get_by_alt_text",
            "get_by_title",
            "get_by_test_id",
        }
    )
    _CHAIN_PROPERTIES: FrozenSet[str] = frozenset({"first", "last"})
    _INTERACTION_METHODS: FrozenSet[str] = frozenset(
        {"click", "dblclick", "tap", "check", "uncheck", "select_option", "set_checked"}
    )

    def __init__(self, locator: Any, guard: "PageGuard"):
        object.__setattr__(self, "_locator", locator)
        object.__setattr__(self, "_guard", guard)

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("_"):
            return object.__getattribute__(self, name)

        locator = object.__getattribute__(self, "_locator")
        guard = object.__getattribute__(self, "_guard")
        chain_methods = object.__getattribute__(self, "_CHAIN_METHODS")
        chain_properties = object.__getattribute__(self, "_CHAIN_PROPERTIES")
        interaction_methods = object.__getattribute__(self, "_INTERACTION_METHODS")

        try:
            attr = getattr(locator, name)
        except AttributeError as exc:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            ) from exc

        if name in chain_properties:
            return GuardedLocator(attr, guard)

        if name in chain_methods:

            @functools.wraps(attr)
            def chain_wrapper(*args: Any, **kwargs: Any) -> Any:
                processed_args = [
                    (
                        object.__getattribute__(arg, "_locator")
                        if isinstance(arg, GuardedLocator)
                        else arg
                    )
                    for arg in args
                ]
                return GuardedLocator(attr(*processed_args, **kwargs), guard)

            return chain_wrapper

        if name in interaction_methods:

            @functools.wraps(attr)
            async def interaction_wrapper(*args: Any, **kwargs: Any) -> Any:
                await guard.wait_until_idle()
                result = await attr(*args, **kwargs)
                await asyncio.sleep(0.1)
                await guard.wait_until_idle()
                return result

            return interaction_wrapper

        if name == "press":

            @functools.wraps(attr)
            async def press_wrapper(key: str, *args: Any, **kwargs: Any) -> None:
                await guard.wait_until_idle()
                await attr(key, *args, **kwargs)
                if key.lower() in ("enter", "return"):
                    await asyncio.sleep(0.1)
                    await guard.wait_until_idle()

            return press_wrapper

        if asyncio.iscoroutinefunction(attr):

            @functools.wraps(attr)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                await guard.wait_until_idle()
                return await attr(*args, **kwargs)

            return async_wrapper

        return attr


__all__ = ["GuardedPage"]

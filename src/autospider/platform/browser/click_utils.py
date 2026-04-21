"""共享的点击工具类。

目标：集中处理“点击 + 新页面检测”，以避免 ActionExecutor 和 collector 代码在多处重复实现。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Locator

from .page_handle import coerce_context_pages


async def _capture_new_page_after_action(
    *,
    page: Any,
    action: Callable[[], Awaitable[None]],
    expect_page_timeout_ms: int,
    load_state: str,
    load_timeout_ms: int,
) -> Any | None:
    pages_before = len(coerce_context_pages(page))
    new_page = None
    await action()

    wait_seconds = max(0.0, expect_page_timeout_ms / 1000)
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            pages = coerce_context_pages(page)
            if len(pages) > pages_before:
                new_page = pages[-1]
                break
        except Exception:
            break
        await asyncio.sleep(0.05)

    if new_page is not None:
        try:
            await new_page.wait_for_load_state(load_state, timeout=load_timeout_ms)
        except Exception:
            pass

    return new_page


async def click_and_capture_new_page(
    *,
    page: Any,
    locator: "Locator",
    click_timeout_ms: int = 5000,
    expect_page_timeout_ms: int = 3000,
    load_state: str = "domcontentloaded",
    load_timeout_ms: int = 10000,
) -> Any | None:
    """点击定位器并捕获新打开的页面（如果有）。

    说明：
    - 点击后短时间轮询 context.pages，检测是否出现新页面。
    - 不使用 expect_page，避免事件 future 在关闭阶段残留未消费异常。
    - 此助手函数仅返回新页面；它不会切换或关闭页面。
    """
    async def _click() -> None:
        await locator.click(timeout=click_timeout_ms)

    return await _capture_new_page_after_action(
        page=page,
        action=_click,
        expect_page_timeout_ms=expect_page_timeout_ms,
        load_state=load_state,
        load_timeout_ms=load_timeout_ms,
    )


async def press_and_capture_new_page(
    *,
    page: Any,
    locator: "Locator",
    key: str,
    press_timeout_ms: int = 5000,
    expect_page_timeout_ms: int = 3000,
    load_state: str = "domcontentloaded",
    load_timeout_ms: int = 10000,
) -> Any | None:
    """按键并捕获新打开的页面（如果有）。

    说明：
    - 优先使用 locator.press；失败时回退到 page.keyboard.press。
    - 通过轮询 context.pages 检测新页面，避免 expect_page 相关 future 噪音。
    - 此助手函数仅返回新页面；它不会切换或关闭页面。
    """
    async def _press() -> None:
        try:
            await locator.press(key, timeout=press_timeout_ms)
        except Exception:
            # 如果元素无法直接接收按键，尝试使用全局键盘模拟
            try:
                await page.keyboard.press(key)
            except Exception:
                pass

    return await _capture_new_page_after_action(
        page=page,
        action=_press,
        expect_page_timeout_ms=expect_page_timeout_ms,
        load_state=load_state,
        load_timeout_ms=load_timeout_ms,
    )

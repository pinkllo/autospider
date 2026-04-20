"""共享的点击工具类。

目标：集中处理“点击 + 新页面检测”，以避免 ActionExecutor 和 collector 代码在多处重复实现。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page
    from .guarded_page import GuardedPage


async def click_and_capture_new_page(
    *,
    page: "Page | GuardedPage",
    locator: "Locator",
    click_timeout_ms: int = 5000,
    expect_page_timeout_ms: int = 3000,
    load_state: str = "domcontentloaded",
    load_timeout_ms: int = 10000,
) -> "Page | GuardedPage | None":
    """点击定位器并捕获新打开的页面（如果有）。

    说明：
    - 点击后短时间轮询 context.pages，检测是否出现新页面。
    - 不使用 expect_page，避免事件 future 在关闭阶段残留未消费异常。
    - 此助手函数仅返回新页面；它不会切换或关闭页面。
    """
    # 获取当前上下文和页面数量，用于后续对比
    context = page.context
    pages_before = len(context.pages)

    new_page: "Page | None" = None
    await locator.click(timeout=click_timeout_ms)

    # 通过轮询页面数量检测新标签页，避免 expect_page 在关闭阶段残留未消费 Future。
    wait_seconds = max(0.0, expect_page_timeout_ms / 1000)
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            if len(context.pages) > pages_before:
                new_page = context.pages[-1]
                break
        except Exception:
            break
        await asyncio.sleep(0.05)

    if new_page is not None:
        try:
            # 等待新页面达到指定的加载状态（默认是 domcontentloaded）
            await new_page.wait_for_load_state(load_state, timeout=load_timeout_ms)
        except Exception:
            # 加载状态等待超时通常不影响页面对象的使用，因此捕获并忽略
            pass

    return new_page


async def press_and_capture_new_page(
    *,
    page: "Page | GuardedPage",
    locator: "Locator",
    key: str,
    press_timeout_ms: int = 5000,
    expect_page_timeout_ms: int = 3000,
    load_state: str = "domcontentloaded",
    load_timeout_ms: int = 10000,
) -> "Page | GuardedPage | None":
    """按键并捕获新打开的页面（如果有）。

    说明：
    - 优先使用 locator.press；失败时回退到 page.keyboard.press。
    - 通过轮询 context.pages 检测新页面，避免 expect_page 相关 future 噪音。
    - 此助手函数仅返回新页面；它不会切换或关闭页面。
    """
    context = page.context
    pages_before = len(context.pages)

    new_page: "Page | None" = None
    try:
        await locator.press(key, timeout=press_timeout_ms)
    except Exception:
        # 如果元素无法直接接收按键，尝试使用全局键盘模拟
        try:
            await page.keyboard.press(key)
        except Exception:
            pass

    wait_seconds = max(0.0, expect_page_timeout_ms / 1000)
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            if len(context.pages) > pages_before:
                new_page = context.pages[-1]
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

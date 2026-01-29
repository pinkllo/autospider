"""共享的点击工具类。

目标：集中处理“点击 + 新页面检测”，以避免 ActionExecutor 和 collector 代码在多处重复实现。
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
    """点击定位器并捕获新打开的页面（如果有）。

    说明：
    - 优先使用 context.expect_page 监听新页面事件。
    - 如果 expect_page 超时但页面数量增加，则回退到最后一个页面，作为延迟打开检测的兜底方案。
    - 此助手函数仅返回新页面；它不会切换或关闭页面。
    """
    # 获取当前上下文和页面数量，用于后续对比
    context = page.context
    pages_before = len(context.pages)

    new_page: "Page | None" = None
    try:
        # 使用 context.expect_page 开启异步监听
        # 这种方式比先点击再检查更可靠，因为它可以捕获点击瞬间触发的新页面事件
        async with context.expect_page(timeout=expect_page_timeout_ms) as new_page_info:
            await locator.click(timeout=click_timeout_ms)
        # 获取新页面的对象
        new_page = await new_page_info.value
    except PlaywrightTimeout:
        # 如果在 expect_page_timeout_ms 内没有捕获到新页面事件，则忽略超时异常
        pass

    # 兜底逻辑：如果 expect_page 没捕获到（可能是事件触发太晚或浏览器行为特殊），
    # 但此时页面总数确实增加了，我们假设最后一个页面就是点击产生的新页面。
    if new_page is None and len(context.pages) > pages_before:
        new_page = context.pages[-1]

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
    - 如果 expect_page 超时但页面数量增加，则回退到最后一个页面。
    - 此助手函数仅返回新页面；它不会切换或关闭页面。
    """
    context = page.context
    pages_before = len(context.pages)

    new_page: "Page | None" = None
    try:
        async with context.expect_page(timeout=expect_page_timeout_ms) as new_page_info:
            await locator.press(key, timeout=press_timeout_ms)
        new_page = await new_page_info.value
    except PlaywrightTimeout:
        pass
    except Exception:
        # 如果元素无法直接接收按键，尝试使用全局键盘模拟
        try:
            async with context.expect_page(timeout=expect_page_timeout_ms) as new_page_info:
                await page.keyboard.press(key)
            new_page = await new_page_info.value
        except PlaywrightTimeout:
            pass
        except Exception:
            pass

    # 兜底：按键触发新标签页但 expect_page 未捕获
    if new_page is None and len(context.pages) > pages_before:
        new_page = context.pages[-1]

    if new_page is not None:
        try:
            await new_page.wait_for_load_state(load_state, timeout=load_timeout_ms)
        except Exception:
            pass

    return new_page

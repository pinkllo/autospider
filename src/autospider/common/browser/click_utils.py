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

    if new_page is not None:
        # 确保返回的页面被 GuardedPage 包装，以便统一管理页面生命周期和异常
        new_page = _ensure_guarded_page(new_page)

    return new_page


def _ensure_guarded_page(page: "Page | GuardedPage") -> "Page | GuardedPage":
    """确保页面被 GuardedPage 包装。
    
    GuardedPage 提供了一种受保护的页面访问方式，通常用于自动重试、
    错误恢复或确保页面在操作期间不会被意外关闭。
    """
    try:
        # 尝试导入必要的组件，这些组件可能在其他包中
        import browser_manager.handlers as _handlers  # noqa: F401
        from browser_manager.guard import PageGuard
        from browser_manager.guarded_page import GuardedPage
    except Exception:
        # 如果无法导入（例如环境未配置），则回退到返回原始页面对象
        return page

    # 如果已经是 GuardedPage，直接返回
    if isinstance(page, GuardedPage):
        return page

    # 检查原始 Page 对象是否已经有关联的 PageGuard
    guard = getattr(page, "_page_guard", None)
    if guard is None:
        # 如果没有，则创建一个新的 PageGuard 并将其绑定到页面上
        guard = PageGuard()
        guard.attach_to_page(page)
        # 设置标识，标记该页面已被 Guard 处理
        setattr(page, "_guard_attached", True)
        setattr(page, "_page_guard", guard)
    
    # 使用 guard 包装页面并返回
    return GuardedPage(page, guard)

"""浏览器会话管理"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

from playwright.async_api import Page

# 引入新的浏览器引擎
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "common"))
from browser_manager.engine import get_browser_engine, BrowserEngine, shutdown_browser_engine
from browser_manager.guard import PageGuard

from ..config import config

if TYPE_CHECKING:
    from ..types import RunInput


class BrowserSession:
    """浏览器会话管理器 - 兼容层
    
    在内部使用BrowserEngine实现,保持向后兼容的API
    """

    def __init__(
        self,
        headless: bool | None = None,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        slow_mo: int | None = None,
    ):
        self.headless = headless if headless is not None else config.browser.headless
        self.viewport_width = viewport_width or config.browser.viewport_width
        self.viewport_height = viewport_height or config.browser.viewport_height
        self.slow_mo = slow_mo if slow_mo is not None else config.browser.slow_mo

        self._engine: BrowserEngine | None = None
        self._page: Page | None = None
        self._page_context = None

    async def start(self) -> Page:
        """启动浏览器并返回 Page"""
        # 获取全局浏览器引擎
        self._engine = await get_browser_engine(
            headless=self.headless,
            default_timeout=config.browser.timeout_ms,
        )
        
        # 创建页面上下文
        self._page_context = self._engine.page(
            headless=self.headless,
            viewport={
                "width": self.viewport_width,
                "height": self.viewport_height,
            },
            timeout=config.browser.timeout_ms,
            auth_file=str(Path.cwd() / ".auth" / "default.json"),
        )
        
        # 进入上下文获取页面
        self._page = await self._page_context.__aenter__()

        # Enable anomaly guard (login/risk-control, etc.)
        self._attach_guard(self._page)
        try:
            self._page.context.on("page", lambda new_page: self._attach_guard(new_page))
        except Exception:
            # Keep main page usable if context events are not available
            pass
        
        return self._page

    async def stop(self) -> None:
        """关闭浏览器会话"""
        # 退出页面上下文
        if self._page_context:
            try:
                await self._page_context.__aexit__(None, None, None)
            except Exception:
                pass
        
        self._page = None
        self._page_context = None
        # 注意: 不关闭全局引擎,因为它是单例,可能被其他会话使用

    @property
    def page(self) -> Page | None:
        return self._page

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """导航到指定 URL"""
        if not self._page:
            raise RuntimeError("Browser session not started")
        await self._page.goto(url, wait_until=wait_until)

    async def wait_for_stable(self, timeout_ms: int = 3000) -> None:
        """等待页面稳定(网络空闲)"""
        if not self._page:
            return
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            # 超时不算错误,继续执行
            pass

    def _attach_guard(self, page: Page) -> None:
        """Attach guard to a page and block after navigations until handled."""
        if getattr(page, "_guard_attached", False):
            return

        # 触发内置处理器注册（仅副作用）
        import browser_manager.handlers as _handlers  # noqa: F401

        guard = PageGuard()
        guard.attach_to_page(page)

        setattr(page, "_guard_attached", True)
        setattr(page, "_page_guard", guard)

        original_goto = page.goto
        original_go_back = page.go_back
        original_reload = page.reload
        original_wait_for_load_state = page.wait_for_load_state

        async def guarded_goto(*args, **kwargs):
            result = await original_goto(*args, **kwargs)
            await guard.run_inspection(page)
            return result

        async def guarded_go_back(*args, **kwargs):
            result = await original_go_back(*args, **kwargs)
            await guard.run_inspection(page)
            return result

        async def guarded_reload(*args, **kwargs):
            result = await original_reload(*args, **kwargs)
            await guard.run_inspection(page)
            return result

        async def guarded_wait_for_load_state(*args, **kwargs):
            result = await original_wait_for_load_state(*args, **kwargs)
            await guard.run_inspection(page)
            return result

        page.goto = guarded_goto
        page.go_back = guarded_go_back
        page.reload = guarded_reload
        page.wait_for_load_state = guarded_wait_for_load_state


@asynccontextmanager
async def create_browser_session(
    headless: bool | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
    close_engine: bool = False,
) -> AsyncGenerator[BrowserSession, None]:
    """创建浏览器会话的上下文管理器"""
    session = BrowserSession(
        headless=headless,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    try:
        await session.start()
        yield session
    finally:
        await session.stop()
        if close_engine:
            # 修改原因：CLI 单次运行后关闭全局引擎，避免事件循环结束时残留连接导致报错。
            try:
                await shutdown_browser_engine()
            except Exception:
                pass

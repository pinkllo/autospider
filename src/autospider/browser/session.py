"""浏览器会话管理"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from ..config import config

if TYPE_CHECKING:
    from ..types import RunInput


class BrowserSession:
    """浏览器会话管理器"""

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

        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self) -> Page:
        """启动浏览器并返回 Page"""
        self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
        )

        self._context = await self._browser.new_context(
            viewport={
                "width": self.viewport_width,
                "height": self.viewport_height,
            },
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        self._page = await self._context.new_page()

        # 设置默认超时
        self._page.set_default_timeout(config.browser.timeout_ms)

        return self._page

    async def stop(self) -> None:
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    @property
    def page(self) -> Page | None:
        return self._page

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """导航到指定 URL"""
        if not self._page:
            raise RuntimeError("Browser session not started")
        await self._page.goto(url, wait_until=wait_until)

    async def wait_for_stable(self, timeout_ms: int = 3000) -> None:
        """等待页面稳定（网络空闲）"""
        if not self._page:
            return
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            # 超时不算错误，继续执行
            pass


@asynccontextmanager
async def create_browser_session(
    headless: bool | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
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

"""浏览器会话管理"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator

from playwright.async_api import Page

from ..config import config
from .engine import BrowserEngine, get_browser_engine, shutdown_browser_engine
from .guarded_page import GuardedPage
from ...pipeline.runtime_controls import get_browser_budget

if TYPE_CHECKING:
    pass


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
        guard_intervention_mode: str = "blocking",
        guard_thread_id: str = "",
        budget_key: str = "",
        global_browser_budget: int | None = None,
    ):
        self.headless = headless if headless is not None else config.browser.headless
        self.viewport_width = viewport_width or config.browser.viewport_width
        self.viewport_height = viewport_height or config.browser.viewport_height
        self.slow_mo = slow_mo if slow_mo is not None else config.browser.slow_mo
        self.guard_intervention_mode = guard_intervention_mode
        self.guard_thread_id = guard_thread_id
        self.budget_key = str(budget_key or guard_thread_id or "")
        self.global_browser_budget = global_browser_budget

        self._engine: BrowserEngine | None = None
        self._page: Page | GuardedPage | None = None
        self._page_context = None
        self._budget = None

    async def start(self) -> Page | GuardedPage:
        """启动浏览器并返回 Page"""
        if self.global_browser_budget is not None:
            self._budget = await get_browser_budget(
                budget_key=self.budget_key,
                limit=int(self.global_browser_budget),
            )
            await self._budget.acquire()
        # 获取全局浏览器引擎
        self._engine = await get_browser_engine(
            default_headless=self.headless,
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
            auth_file=".auth/default.json",
            guard_intervention_mode=self.guard_intervention_mode,
            guard_thread_id=self.guard_thread_id,
        )

        # 进入上下文获取页面
        self._page = await self._page_context.__aenter__()

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
        if self._budget is not None:
            self._budget.release()
            self._budget = None
        # 注意: 不关闭全局引擎,因为它是单例,可能被其他会话使用

    @property
    def page(self) -> Page | GuardedPage | None:
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

@asynccontextmanager
async def create_browser_session(
    headless: bool | None = None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
    close_engine: bool = False,
    guard_intervention_mode: str = "blocking",
    guard_thread_id: str = "",
    budget_key: str = "",
    global_browser_budget: int | None = None,
) -> AsyncGenerator[BrowserSession, None]:
    """创建浏览器会话的上下文管理器"""
    session = BrowserSession(
        headless=headless,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        guard_intervention_mode=guard_intervention_mode,
        guard_thread_id=guard_thread_id,
        budget_key=budget_key,
        global_browser_budget=global_browser_budget,
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

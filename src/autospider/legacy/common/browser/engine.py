"""
异步浏览器引擎。

提供全局唯一的 Browser 实例管理，并集成 PageGuard 自动监控机制。
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Literal

from playwright.async_api import Browser, Page, Playwright, async_playwright
from autospider.legacy.common.logger import get_logger

from .guard import PageGuard
from .task_utils import create_monitored_task

logger = get_logger(__name__)
try:
    from playwright_stealth import Stealth  # type: ignore
except Exception:
    Stealth = None  # type: ignore

try:
    from playwright_stealth import stealth_async as apply_stealth_async
except Exception:
    apply_stealth_async = None


class BrowserEngine:
    """浏览器引擎单例实现。"""

    def __init__(
        self,
        default_headless: bool = True,
        default_viewport: dict[str, int] | None = None,
        default_user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        default_launch_args: list[str] | None = None,
        default_browser_type: Literal["chromium", "firefox", "webkit"] = "chromium",
        max_retries: int = 2,
        default_timeout: int = 30000,
    ):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._stealth_context: Any | None = None
        self._playwright_started_direct = False
        self._current_headless = default_headless
        self._lock = asyncio.Lock()
        self._owner_loop: asyncio.AbstractEventLoop | None = None

        self.default_headless = default_headless
        self.default_viewport = default_viewport or {"width": 1920, "height": 1080}
        self.default_user_agent = default_user_agent
        self.default_browser_type = default_browser_type
        self.max_retries = max_retries
        self.default_timeout = default_timeout
        self.default_launch_args = default_launch_args or [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-extensions",
            "--no-first-run",
        ]

    async def _ensure_browser(self, headless: bool) -> None:
        current_loop = asyncio.get_running_loop()

        async with self._lock:
            should_restart = False
            if self._browser and self._owner_loop and self._owner_loop != current_loop:
                logger.warning("Event Loop changed. Restarting browser...")
                should_restart = True
            elif not self._browser or not self._browser.is_connected():
                should_restart = True
            elif self._current_headless != headless:
                logger.info(f"Switching Headless Mode: {headless}")
                should_restart = True

            if not should_restart:
                return

            if self._browser and self._owner_loop == current_loop:
                try:
                    await self._browser.close()
                except Exception:
                    pass

            if not self._playwright:
                if Stealth is not None:
                    self._stealth_context = Stealth().use_async(async_playwright())
                    self._playwright = await self._stealth_context.__aenter__()
                    self._playwright_started_direct = False
                else:
                    self._playwright = await async_playwright().start()
                    self._playwright_started_direct = True

            for attempt in range(self.max_retries + 1):
                try:
                    launcher = getattr(self._playwright, self.default_browser_type)
                    self._browser = await launcher.launch(
                        headless=headless,
                        args=self.default_launch_args,
                    )
                    self._current_headless = headless
                    self._owner_loop = current_loop
                    break
                except Exception as exc:
                    if attempt == self.max_retries:
                        raise exc

    @asynccontextmanager
    async def page(
        self,
        auth_file: str | None = None,
        headless: bool | None = None,
        proxy: dict[str, str] | None = None,
        timeout: int | None = None,
        enable_guard: bool = True,
        auto_load_cookie: bool = True,
        guard_intervention_mode: str = "blocking",
        guard_thread_id: str = "",
        handlers: list[object] | None = None,
        **context_kwargs: Any,
    ) -> AsyncGenerator[Page, None]:
        use_headless = headless if headless is not None else self.default_headless
        await self._ensure_browser(use_headless)

        if auth_file is None and auto_load_cookie:
            auth_file = os.path.join(os.getcwd(), ".auth", "default.json")

        options: dict[str, Any] = {
            "viewport": self.default_viewport,
            "user_agent": self.default_user_agent,
            "ignore_https_errors": True,
            **context_kwargs,
        }
        if proxy:
            options["proxy"] = proxy
        if auth_file and os.path.exists(auth_file):
            logger.debug(f"[Engine] 自动加载 Cookie: {auth_file}")
            options["storage_state"] = auth_file

        context = await self._browser.new_context(**options)
        page = await context.new_page()
        page.set_default_timeout(timeout or self.default_timeout)
        if apply_stealth_async is not None:
            try:
                await apply_stealth_async(page)
            except Exception as exc:
                logger.debug(f"[Engine] 应用 stealth_async 失败（可忽略）: {exc}")

        guard = None
        if enable_guard:
            from .guarded_page import GuardedPage

            guard = PageGuard(
                intervention_mode=guard_intervention_mode,
                thread_id=guard_thread_id,
                handlers=handlers,
            )
            guard.attach_to_page(page)
            create_monitored_task(
                guard.run_inspection(page),
                task_name="PageGuard.initial_inspection",
            )

            async def _setup_new_page(new_page: Page) -> None:
                if apply_stealth_async is not None:
                    try:
                        await apply_stealth_async(new_page)
                    except Exception as exc:
                        logger.debug(f"[Engine] 新页面应用 stealth_async 失败（可忽略）: {exc}")
                guard.attach_to_page(new_page)
                create_monitored_task(
                    guard.run_inspection(new_page),
                    task_name="PageGuard.new_page_inspection",
                )

            def _on_new_page(new_page: Page) -> None:
                create_monitored_task(
                    _setup_new_page(new_page),
                    task_name="BrowserEngine.setup_new_page",
                )

            context.on("page", _on_new_page)

        try:
            if enable_guard and guard:
                yield GuardedPage(page, guard)
            else:
                yield page
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass

    async def close(self) -> None:
        current_loop = asyncio.get_running_loop()
        if self._browser and self._owner_loop == current_loop:
            await self._browser.close()
        if self._stealth_context and self._owner_loop == current_loop:
            await self._stealth_context.__aexit__(None, None, None)
        elif (
            self._playwright
            and self._playwright_started_direct
            and self._owner_loop == current_loop
        ):
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._stealth_context = None
        self._playwright_started_direct = False


_browser_engine: BrowserEngine | None = None
_engine_lock = asyncio.Lock()


async def get_browser_engine(**config: Any) -> BrowserEngine:
    """获取全局 BrowserEngine 单例。"""
    global _browser_engine

    async with _engine_lock:
        if _browser_engine is None:
            _browser_engine = BrowserEngine(**config)
        return _browser_engine


async def shutdown_browser_engine() -> None:
    """关闭全局浏览器引擎单例。"""
    global _browser_engine

    engine = _browser_engine
    if engine is None:
        return

    try:
        await engine.close()
    finally:
        _browser_engine = None


__all__ = ["BrowserEngine", "get_browser_engine", "shutdown_browser_engine"]

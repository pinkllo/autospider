"""Browser runtime session abstraction."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import Page

from ...pipeline.types import ExecutionRequest
from ...pipeline.runtime_controls import get_browser_budget
from ..config import config
from .composition import build_default_handlers
from .engine import get_browser_engine, shutdown_browser_engine
from .guarded_page import GuardedPage


class BrowserRuntimeSession:
    """Canonical browser lifecycle abstraction for use cases and pipeline."""

    def __init__(
        self,
        *,
        headless: bool | None = None,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        slow_mo: int | None = None,
        guard_intervention_mode: str = "blocking",
        guard_thread_id: str = "",
        budget_key: str = "",
        global_browser_budget: int | None = None,
        close_engine: bool = False,
    ) -> None:
        self.headless = headless if headless is not None else config.browser.headless
        self.viewport_width = viewport_width or config.browser.viewport_width
        self.viewport_height = viewport_height or config.browser.viewport_height
        self.slow_mo = slow_mo if slow_mo is not None else config.browser.slow_mo
        self.guard_intervention_mode = guard_intervention_mode
        self.guard_thread_id = guard_thread_id
        self.budget_key = str(budget_key or guard_thread_id or "")
        self.global_browser_budget = global_browser_budget
        self.close_engine = close_engine
        self._page = None
        self._page_context = None
        self._budget = None

    @classmethod
    def build_options(cls, request: ExecutionRequest) -> dict[str, object]:
        return {
            "headless": request.headless,
            "guard_intervention_mode": request.guard_intervention_mode,
            "guard_thread_id": request.guard_thread_id,
            "budget_key": request.execution_id or request.guard_thread_id,
            "global_browser_budget": request.global_browser_budget,
        }

    @classmethod
    @asynccontextmanager
    async def from_request(
        cls, request: ExecutionRequest
    ) -> AsyncGenerator["BrowserRuntimeSession", None]:
        session = cls(**cls.build_options(request), close_engine=True)
        try:
            await session.start()
            yield session
        finally:
            await session.stop()

    async def start(self) -> Page | GuardedPage:
        if self.global_browser_budget is not None:
            self._budget = await get_browser_budget(
                budget_key=self.budget_key,
                limit=int(self.global_browser_budget),
            )
            await self._budget.acquire()
        engine = await get_browser_engine(
            default_headless=self.headless,
            default_timeout=config.browser.timeout_ms,
        )
        self._page_context = engine.page(
            headless=self.headless,
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            timeout=config.browser.timeout_ms,
            auth_file=".auth/default.json",
            guard_intervention_mode=self.guard_intervention_mode,
            guard_thread_id=self.guard_thread_id,
            handlers=build_default_handlers(),
        )
        self._page = await self._page_context.__aenter__()
        return self._page

    async def stop(self) -> None:
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
        if self.close_engine:
            try:
                await shutdown_browser_engine()
            except Exception:
                pass

    @property
    def page(self) -> Page | GuardedPage | None:
        return self._page

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> None:
        if not self._page:
            raise RuntimeError("Browser runtime session not started")
        await self._page.goto(url, wait_until=wait_until)

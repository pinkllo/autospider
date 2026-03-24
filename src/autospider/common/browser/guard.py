"""
页面巡检员模块。
"""

from __future__ import annotations

import asyncio

from loguru import logger
from playwright.async_api import Page

from .handlers.base import BaseAnomalyHandler
from .intervention import BrowserInterventionRequired
from .registry import get_handlers
from .task_utils import create_monitored_task


class PageGuard:
    """页面巡检员。"""

    def __init__(self, intervention_mode: str = "blocking", thread_id: str = ""):
        self.intervention_mode = intervention_mode
        self.thread_id = thread_id
        self._is_handling = False
        self._lock = asyncio.Lock()
        self._poll_tasks: dict[int, asyncio.Task] = {}
        self._poll_interval_s = 1.0
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self._pending_intervention: BrowserInterventionRequired | None = None

    async def run_inspection(self, page: Page) -> None:
        if self._is_handling:
            logger.debug("[PageGuard] 跳过巡检：已在处理中")
            return

        async with self._lock:
            if self._is_handling:
                return

            handlers = get_handlers()
            for handler in handlers:
                try:
                    if await handler.detect(page):
                        logger.warning(f"[PageGuard] 检测到异常状态: {handler.name}")
                        self._is_handling = True
                        self._idle_event.clear()
                        logger.debug("[PageGuard] _idle_event.clear() - 开始阻塞")

                        try:
                            await handler.handle(page)
                            if self._pending_intervention is None:
                                await self._refresh_context_pages(page, source_handler=handler.name)
                        except BrowserInterventionRequired as exc:
                            self._pending_intervention = exc
                            logger.warning(f"[PageGuard] 异常状态已转换为 interrupt: {handler.name}")
                        finally:
                            self._is_handling = False
                            self._idle_event.set()
                            logger.debug("[PageGuard] _idle_event.set() - 解除阻塞")

                        break
                except Exception as exc:
                    self._is_handling = False
                    self._idle_event.set()
                    logger.error(f"[PageGuard] 处理器 {handler.name} 运行出错: {exc}")

    async def _refresh_context_pages(self, page: Page, source_handler: str) -> None:
        try:
            pages = list(page.context.pages)
        except Exception as exc:
            logger.debug(f"[PageGuard] 获取 context.pages 失败（忽略）: {exc}")
            return

        if not pages:
            return

        logger.info(
            f"[PageGuard] 异常处理完成（{source_handler}），开始刷新当前 context 全部页面: {len(pages)} 个"
        )
        for current_page in pages:
            try:
                if current_page.is_closed():
                    continue
                await current_page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                logger.debug(f"[PageGuard] 刷新页面失败（忽略）: {exc}")

    async def wait_until_idle(self) -> None:
        await self._idle_event.wait()
        pending = self._pending_intervention
        if pending is not None:
            self._pending_intervention = None
            raise pending

    def attach_to_page(self, page: Page) -> None:
        try:
            if getattr(page, "_guard_attached", False):
                return
        except Exception:
            pass

        login_keywords = ["login", "passport", "signin", "member", "auth"]

        def should_inspect(frame) -> bool:
            if frame == page.main_frame:
                return True
            frame_url = frame.url.lower()
            return any(keyword in frame_url for keyword in login_keywords)

        try:
            setattr(page, "_page_guard", self)
            setattr(page, "_guard_attached", True)
        except Exception:
            pass

        page.on(
            "framenavigated",
            lambda frame: create_monitored_task(
                self.run_inspection(page),
                task_name="PageGuard.framenavigated_inspection",
            )
            if should_inspect(frame)
            else None,
        )
        page.on(
            "domcontentloaded",
            lambda: create_monitored_task(
                self.run_inspection(page),
                task_name="PageGuard.domcontentloaded_inspection",
            ),
        )
        self._ensure_polling(page)

    def _ensure_polling(self, page: Page) -> None:
        page_id = id(page)
        task = self._poll_tasks.get(page_id)
        if task and not task.done():
            return
        self._poll_tasks[page_id] = create_monitored_task(
            self._poll_page(page),
            task_name="PageGuard.poll_page",
        )

    async def _poll_page(self, page: Page) -> None:
        page_id = id(page)
        try:
            while True:
                try:
                    if page.is_closed():
                        break
                except Exception:
                    break

                try:
                    await self.run_inspection(page)
                except Exception as exc:
                    logger.debug(f"[PageGuard] 轮询巡检异常（忽略）: {exc}")

                await asyncio.sleep(self._poll_interval_s)
        finally:
            self._poll_tasks.pop(page_id, None)


async def ensure_guard_idle(page: Page) -> None:
    """确保 Guard 空闲。"""
    try:
        from .guarded_page import GuardedPage

        if isinstance(page, GuardedPage):
            guard = object.__getattribute__(page, "_guard")
            await guard.wait_until_idle()
            return

        guard = getattr(page, "_page_guard", None)
        if guard is not None:
            await guard.wait_until_idle()
    except Exception as exc:
        logger.debug(f"[ensure_guard_idle] 等待失败（可忽略）: {exc}")


__all__ = ["PageGuard", "BaseAnomalyHandler", "ensure_guard_idle"]

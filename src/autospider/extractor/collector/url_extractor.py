"""URL 提取模块 - 负责从元素中提取 URL"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from ...common.browser.actions import ActionExecutor
from ...common.browser.click_utils import click_and_capture_new_page
from ...common.som import build_mark_id_to_xpath_map, set_overlay_visibility
from ...common.types import Action, ActionType

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ...common.types import ElementMark, SoMSnapshot


class URLExtractor:
    """URL 提取器，负责从页面元素中提取详情页 URL"""
    
    def __init__(self, page: "Page", list_url: str):
        self.page = page
        self.list_url = list_url
    
    async def extract_from_element(
        self, 
        element: "ElementMark",
        snapshot: "SoMSnapshot",
        nav_steps: list[dict] | None = None,
    ) -> str | None:
        """从元素中提取 URL（优先从 href，否则点击获取）"""
        # 策略 1: 先尝试从 href 提取
        if element.href:
            url = urljoin(self.list_url, element.href)
            print(f"[Extract] ✓ 从 href 提取: {url[:60]}...")
            return url
        
        # 策略 2: 点击获取
        print(f"[Extract] 元素无 href，点击获取 URL...")
        return await self.click_and_get_url(element, snapshot, nav_steps=nav_steps)
    
    async def click_and_get_url(
        self,
        element: "ElementMark",
        snapshot: "SoMSnapshot",
        nav_steps: list[dict] | None = None,
    ) -> str | None:
        """点击元素并获取新页面的 URL"""
        list_url = self.page.url
        print(f"[Click] 当前 URL: {list_url[:60]}...")

        try:
            await set_overlay_visibility(self.page, False)

            mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)
            executor = ActionExecutor(self.page)

            result, _ = await executor.execute(
                Action(action=ActionType.CLICK, mark_id=element.mark_id, timeout_ms=5000),
                mark_id_to_xpath,
                step_index=0,
            )
            if not result.success:
                print(f"[Click] ✗ 点击失败: {result.error}")
                return None

            new_page = getattr(executor, "_new_page", None)
            if new_page is not None:
                new_url = new_page.url
                print(f"[Click] ✓ 检测到新标签页: {new_url[:60]}...")
                try:
                    await new_page.close()
                except Exception:
                    pass
                executor._new_page = None
                return new_url

            # Same-tab navigation
            await asyncio.sleep(2)
            new_url = self.page.url
            old_parsed = urlparse(list_url)
            new_parsed = urlparse(new_url)

            print(f"[Click] 旧 URL: {list_url}")
            print(f"[Click] 新 URL: {new_url}")

            if new_url != list_url or old_parsed.fragment != new_parsed.fragment:
                print(f"[Click] ✓ URL 已变化")
                print(f"[Click] 返回列表页...")
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
                if nav_steps:
                    from .navigation_handler import NavigationHandler

                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)
                return new_url

            print(f"[Click] ✗ URL 未变化")
            try:
                await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
                await asyncio.sleep(1)
            except Exception:
                try:
                    await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(1)
                    if nav_steps:
                        from .navigation_handler import NavigationHandler

                        nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                        await nav_handler.replay_nav_steps(nav_steps)
                except Exception:
                    pass

            return None
        except Exception as e:
            print(f"[Click] ✗ 点击失败: {e}")
            try:
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
                if nav_steps:
                    from .navigation_handler import NavigationHandler

                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)
            except Exception:
                pass
            return None
    
    async def click_element_and_get_url(self, element_locator, nav_steps: list[dict] = None) -> str | None:
        """点击 playwright 元素并获取新页面的 URL（用于收集阶段）"""
        from .navigation_handler import NavigationHandler
        
        list_url = self.page.url
        
        try:
            new_page = await click_and_capture_new_page(
                page=self.page,
                locator=element_locator,
                click_timeout_ms=5000,
                expect_page_timeout_ms=3000,
                load_state="domcontentloaded",
                load_timeout_ms=10000,
            )
            if new_page is not None:
                new_url = new_page.url
                await new_page.close()
                return new_url

            await asyncio.sleep(2)
            new_url = self.page.url

            # 检查 URL 或 hash 是否变化
            old_parsed = urlparse(list_url)
            new_parsed = urlparse(new_url)

            if new_url != list_url or old_parsed.fragment != new_parsed.fragment:
                # URL 已变化，返回列表页
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)

                # 重新执行导航步骤
                if nav_steps:
                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)

                return new_url

            try:
                await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
                await asyncio.sleep(1)
            except Exception:
                try:
                    await self.page.goto(
                        self.list_url,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await asyncio.sleep(1)
                    if nav_steps:
                        nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                        await nav_handler.replay_nav_steps(nav_steps)
                except Exception:
                    pass

            return None
                
        except Exception as e:
            print(f"[Collect-XPath] 点击失败: {e}")
            try:
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
                if nav_steps:
                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)
            except Exception:
                pass
            return None

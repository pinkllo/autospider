"""URL 提取模块 - 负责从元素中提取 URL"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from ...common.som import set_overlay_visibility

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
        return await self.click_and_get_url(element, nav_steps=nav_steps)
    
    async def click_and_get_url(
        self,
        element: "ElementMark",
        nav_steps: list[dict] | None = None,
    ) -> str | None:
        """点击元素并获取新页面的 URL"""
        list_url = self.page.url
        context = self.page.context
        pages_before = len(context.pages)
        
        print(f"[Click] 当前 URL: {list_url[:60]}...")
        print(f"[Click] 当前标签页数: {pages_before}")
        
        try:
            # 隐藏覆盖层
            await set_overlay_visibility(self.page, False)
            
            # 策略1: 优先使用 data-som-id
            locator = self.page.locator(f'[data-som-id="{element.mark_id}"]')
            element_found = await locator.count() > 0
            
            # 策略2: 如果 data-som-id 失效(DOM更新/滚动导致),使用 XPath 后备
            if not element_found and element.xpath_candidates:
                print(f"[Click] data-som-id失效,尝试XPath后备...")
                # 按优先级尝试xpath
                for candidate in sorted(element.xpath_candidates, key=lambda x: x.priority):
                    try:
                        xpath_locator = self.page.locator(f"xpath={candidate.xpath}")
                        if await xpath_locator.count() > 0:
                            locator = xpath_locator
                            element_found = True
                            print(f"[Click] ✓ XPath成功: {candidate.xpath[:60]}...")
                            break
                    except Exception:
                        continue
            
            if element_found:
                print(f"[Click] 点击元素 [{element.mark_id}]...")
                
                # 尝试监听新标签页
                try:
                    async with context.expect_page(timeout=3000) as new_page_info:
                        await locator.first.click(timeout=5000)
                    
                    # 有新标签页打开
                    new_page = await new_page_info.value
                    await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                    new_url = new_page.url
                    print(f"[Click] ✓ 检测到新标签页: {new_url[:60]}...")
                    
                    # 关闭新标签页
                    await new_page.close()
                    return new_url
                    
                except Exception:
                    # 没有新标签页，可能是当前页面导航
                    print(f"[Click] 未检测到新标签页，检查当前页面 URL...")
                    await asyncio.sleep(3)
                    
                    new_url = self.page.url
                    pages_after = len(context.pages)
                    
                    old_parsed = urlparse(list_url)
                    new_parsed = urlparse(new_url)
                    
                    print(f"[Click] 旧 URL: {list_url}")
                    print(f"[Click] 新 URL: {new_url}")
                    
                    # 检查是否打开了新标签页（延迟打开）
                    if pages_after > pages_before:
                        print(f"[Click] 检测到新标签页（延迟打开）")
                        all_pages = context.pages
                        new_page = all_pages[-1]
                        await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                        new_url = new_page.url
                        print(f"[Click] ✓ 从新标签页获取 URL: {new_url[:60]}...")
                        
                        await new_page.close()
                        return new_url
                    
                    # 检查 URL 或 hash 是否变化
                    if new_url != list_url or old_parsed.fragment != new_parsed.fragment:
                        print(f"[Click] ✓ URL 已变化")
                        
                        # 返回列表页
                        print(f"[Click] 返回列表页...")
                        await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(1)
                        if nav_steps:
                            from .navigation_handler import NavigationHandler
                            
                            nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                            await nav_handler.replay_nav_steps(nav_steps)
                        
                        return new_url
                    else:
                        print(f"[Click] ✗ URL 未变化")
                        try:
                            await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
                            await asyncio.sleep(1)
                            return None
                        except Exception:
                            try:
                                await self.page.goto(
                                    self.list_url,
                                    wait_until="domcontentloaded",
                                    timeout=30000,
                                )
                                await asyncio.sleep(1)
                                if nav_steps:
                                    from .navigation_handler import NavigationHandler
                                    
                                    nav_handler = NavigationHandler(
                                        self.page, self.list_url, "", 10
                                    )
                                    await nav_handler.replay_nav_steps(nav_steps)
                            except Exception:
                                pass
                        return None
            else:
                print(f"[Click] ✗ 找不到元素 {element.mark_id}")
        except Exception as e:
            print(f"[Click] ✗ 点击失败: {e}")
            # 尝试返回列表页
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
        context = self.page.context
        pages_before = len(context.pages)
        
        try:
            # 尝试监听新标签页
            try:
                async with context.expect_page(timeout=3000) as new_page_info:
                    await element_locator.click(timeout=5000)
                
                new_page = await new_page_info.value
                await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                new_url = new_page.url
                await new_page.close()
                return new_url
                
            except Exception:
                await asyncio.sleep(2)
                
                new_url = self.page.url
                pages_after = len(context.pages)
                
                # 检查是否打开了新标签页（延迟打开）
                if pages_after > pages_before:
                    all_pages = context.pages
                    new_page = all_pages[-1]
                    await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                    new_url = new_page.url
                    await new_page.close()
                    return new_url
                
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

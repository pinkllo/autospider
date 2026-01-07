"""分页处理模块 - 负责分页控件识别和翻页操作"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING

from ..config import config
from ..som import clear_overlay, inject_and_scan, capture_screenshot_with_marks

if TYPE_CHECKING:
    from pathlib import Path
    from playwright.async_api import Page
    from .llm_decision import LLMDecisionMaker


class PaginationHandler:
    """分页处理器，负责识别和操作分页控件"""
    
    def __init__(
        self,
        page: "Page",
        list_url: str,
        screenshots_dir: "Path" = None,
        llm_decision_maker: "LLMDecisionMaker" = None,
    ):
        self.page = page
        self.list_url = list_url
        self.screenshots_dir = screenshots_dir
        self.llm_decision_maker = llm_decision_maker
        self.pagination_xpath: str | None = None
        self.current_page_num = 1
    
    async def extract_pagination_xpath(self) -> str | None:
        """
        在探索阶段提取分页控件的 xpath
        
        通过扫描页面查找下一页按钮，并记录其 xpath
        """
        print(f"[Extract-Pagination] 开始提取分页控件 xpath...")
        
        # 常见的下一页选择器
        common_selectors = [
            'a:has-text("下一页")',
            'button:has-text("下一页")',
            'a:has-text("next")',
            'button:has-text("next")',
            'a:has-text(">")',
            '[class*="next"]',
            '[class*="pagination"] a:last-child',
        ]
        
        for selector in common_selectors:
            try:
                locator = self.page.locator(selector)
                if await locator.count() > 0:
                    print(f"[Extract-Pagination] 找到分页按钮: {selector}")
                    
                    # 尝试获取 xpath（通过评估）
                    # 这里简化处理，实际应该从 SoM 中获取
                    self.pagination_xpath = selector
                    return selector
            except Exception:
                continue
        
        # 如果常规选择器都失败，尝试用 LLM 视觉识别
        if self.llm_decision_maker:
            print(f"[Extract-Pagination] 常规选择器未找到，尝试 LLM 视觉识别...")
            return await self.extract_pagination_xpath_with_llm()
        
        return None
    
    async def extract_pagination_xpath_with_llm(self) -> str | None:
        """使用 LLM 视觉识别分页控件并提取 xpath"""
        if not self.llm_decision_maker:
            return None
        
        try:
            # 截图
            await clear_overlay(self.page)
            snapshot = await inject_and_scan(self.page)
            screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            
            # 保存截图
            if self.screenshots_dir:
                screenshot_path = self.screenshots_dir / "pagination_extract.png"
                screenshot_path.write_bytes(screenshot_bytes)
            
            # 使用 LLM 识别分页控件
            data = await self.llm_decision_maker.extract_pagination_with_llm(snapshot, screenshot_base64)
            
            if data and data.get("found") and data.get("mark_id"):
                mark_id = data["mark_id"]
                print(f"[Extract-Pagination-LLM] 找到分页按钮 [{mark_id}]: {data.get('reasoning', '')}")
                
                # 找到对应的元素，获取其 xpath
                element = next((m for m in snapshot.marks if m.mark_id == mark_id), None)
                if element and element.xpath_candidates:
                    # 取优先级最高的 xpath
                    sorted_candidates = sorted(element.xpath_candidates, key=lambda x: x.priority)
                    best_xpath = sorted_candidates[0].xpath if sorted_candidates else None
                    
                    if best_xpath:
                        self.pagination_xpath = best_xpath
                        print(f"[Extract-Pagination-LLM] ✓ 提取到 xpath: {best_xpath}")
                        return best_xpath
            else:
                print(f"[Extract-Pagination-LLM] 未找到分页按钮: {data.get('reasoning', '') if data else ''}")
        except Exception as e:
            print(f"[Extract-Pagination-LLM] LLM 识别失败: {e}")
        
        print(f"[Extract-Pagination] ⚠ 未能提取分页控件 xpath")
        return None
    
    async def find_and_click_next_page(self) -> bool:
        """
        查找并点击下一页按钮
        
        优先使用探索阶段提取的 pagination_xpath，如果没有则尝试常见选择器
        
        Returns:
            是否成功翻页
        """
        # 策略1: 使用提取的 pagination_xpath
        if self.pagination_xpath:
            try:
                # 检查是否是 xpath
                if self.pagination_xpath.startswith('//') or self.pagination_xpath.startswith('('):
                    locator = self.page.locator(f"xpath={self.pagination_xpath}")
                else:
                    locator = self.page.locator(self.pagination_xpath)
                
                if await locator.count() > 0:
                    print(f"[Pagination] 使用提取的 xpath 点击下一页...")
                    
                    # 获取随机延迟
                    from ..utils import get_random_delay
                    delay = get_random_delay(
                        config.crawler.action_delay_base,
                        config.crawler.action_delay_random
                    )
                    await asyncio.sleep(delay)
                    
                    await locator.first.click(timeout=5000)
                    await asyncio.sleep(config.crawler.page_load_delay)
                    
                    self.current_page_num += 1
                    print(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                    return True
            except Exception as e:
                print(f"[Pagination] 使用提取的 xpath 失败: {e}")
        
        # 策略2: 尝试常见选择器
        common_selectors = [
            'a:has-text("下一页")',
            'button:has-text("下一页")',
            'a:has-text("next")',
            'button:has-text("next")',
            '[class*="next"]:not([class*="disabled"])',
        ]
        
        for selector in common_selectors:
            try:
                locator = self.page.locator(selector)
                if await locator.count() > 0:
                    print(f"[Pagination] 使用常规选择器点击: {selector}")
                    await locator.first.click(timeout=5000)
                    await asyncio.sleep(1)
                    
                    self.current_page_num += 1
                    print(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                    return True
            except Exception:
                continue
        
        print(f"[Pagination] ⚠ 未找到下一页按钮")
        return False
    
    async def find_next_page_with_llm(self, screenshot_base64: str = None) -> bool:
        """
        使用 LLM 视觉识别并点击下一页按钮
        
        Returns:
            是否成功翻页
        """
        if not self.llm_decision_maker:
            return False
        
        try:
            # 如果没有提供截图，重新截图
            if not screenshot_base64:
                await clear_overlay(self.page)
                snapshot = await inject_and_scan(self.page)
                screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            else:
                snapshot = await inject_and_scan(self.page)
            
            # 使用 LLM 识别下一页按钮
            data = await self.llm_decision_maker.extract_pagination_with_llm(snapshot, screenshot_base64)
            
            if data and data.get("found") and data.get("mark_id"):
                mark_id = data["mark_id"]
                print(f"[Pagination-LLM] 找到下一页按钮 [{mark_id}]")
                
                # 点击
                locator = self.page.locator(f'[data-som-id="{mark_id}"]')
                if await locator.count() > 0:
                    await locator.first.click(timeout=5000)
                    await asyncio.sleep(1)
                    
                    self.current_page_num += 1
                    print(f"[Pagination-LLM] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                    return True
            else:
                print(f"[Pagination-LLM] 未找到下一页: {data.get('reasoning', '') if data else ''}")
        except Exception as e:
            print(f"[Pagination-LLM] LLM 识别失败: {e}")
        
        return False

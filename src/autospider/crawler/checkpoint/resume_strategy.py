"""断点恢复策略模块

实现三级断点定位策略：
1. URLPatternStrategy - URL 规律爆破
2. WidgetJumpStrategy - 控件直达
3. SmartSkipStrategy - 首项检测与回溯
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

if TYPE_CHECKING:
    from playwright.async_api import Page


def _is_xpath_selector(selector: str | None) -> bool:
    if not selector:
        return False
    stripped = selector.strip()
    return stripped.startswith("xpath=") or stripped.startswith("//") or stripped.startswith("(")


def _build_locator(page: "Page", selector: str | None):
    if not selector:
        return None
    stripped = selector.strip()
    if stripped.startswith("xpath="):
        return page.locator(stripped)
    if _is_xpath_selector(stripped):
        return page.locator(f"xpath={stripped}")
    return page.locator(stripped)


class ResumeStrategy(ABC):
    """恢复策略基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass
    
    @abstractmethod
    async def try_resume(self, page: "Page", target_page: int) -> tuple[bool, int]:
        """尝试恢复到目标页
        
        Args:
            page: Playwright Page 对象
            target_page: 目标页码
            
        Returns:
            (是否成功, 实际到达的页码)
        """
        pass


class URLPatternStrategy(ResumeStrategy):
    """策略一: URL 规律爆破
    
    分析列表页 URL 是否包含 page=xx 参数，直接构造跳转。
    """
    
    def __init__(self, list_url: str):
        """初始化
        
        Args:
            list_url: 列表页 URL
        """
        self.list_url = list_url
        self.page_param = self._detect_page_param()
    
    @property
    def name(self) -> str:
        return "URL规律爆破"
    
    def _detect_page_param(self) -> str | None:
        """检测 URL 中的页码参数名"""
        parsed = urlparse(self.list_url)
        params = parse_qs(parsed.query)
        
        # 常见的页码参数名
        common_page_params = ["page", "p", "pageNum", "pageNo", "pn", "offset"]
        
        for param in common_page_params:
            if param in params:
                return param
        
        return None
    
    def _build_url_for_page(self, target_page: int) -> str | None:
        """构造目标页的 URL"""
        if not self.page_param:
            return None
        
        parsed = urlparse(self.list_url)
        params = parse_qs(parsed.query)
        params[self.page_param] = [str(target_page)]
        
        new_query = urlencode(params, doseq=True)
        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))
        
        return new_url
    
    async def try_resume(self, page: "Page", target_page: int) -> tuple[bool, int]:
        """尝试通过 URL 直接跳转"""
        if not self.page_param:
            print(f"[{self.name}] URL 中未检测到页码参数")
            return False, 1
        
        target_url = self._build_url_for_page(target_page)
        if not target_url:
            return False, 1
        
        print(f"[{self.name}] 尝试跳转到: {target_url}")
        
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            
            # 验证是否真的跳转成功（检查 URL 是否包含目标页码）
            current_url = page.url
            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            
            if self.page_param in params:
                current_page = int(params[self.page_param][0])
                if current_page == target_page:
                    print(f"[{self.name}] ✓ 成功跳转到第 {target_page} 页")
                    return True, target_page
            
            print(f"[{self.name}] 跳转后验证失败，URL 可能被重定向")
            return False, 1
            
        except Exception as e:
            print(f"[{self.name}] 跳转失败: {e}")
            return False, 1


class WidgetJumpStrategy(ResumeStrategy):
    """策略二: 页码控件直达
    
    使用 Phase 3.6 提取的跳转控件 xpath 进行跳转。
    """
    
    def __init__(self, jump_widget_xpath: dict[str, str] | None = None):
        """初始化
        
        Args:
            jump_widget_xpath: {"input": "xpath", "button": "xpath"}
        """
        self.jump_widget_xpath = jump_widget_xpath
    
    @property
    def name(self) -> str:
        return "控件直达"
    
    async def try_resume(self, page: "Page", target_page: int) -> tuple[bool, int]:
        """尝试通过页码输入控件跳转"""
        if not self.jump_widget_xpath:
            print(f"[{self.name}] 未提供跳转控件 xpath")
            return False, 1
        
        input_xpath = self.jump_widget_xpath.get("input")
        button_xpath = self.jump_widget_xpath.get("button")
        
        if not input_xpath or not button_xpath:
            print(f"[{self.name}] 跳转控件 xpath 不完整")
            return False, 1
        
        try:
            input_locator = _build_locator(page, input_xpath)
            if not input_locator or await input_locator.count() == 0:
                print(f"[{self.name}] 未找到页码输入框")
                return False, 1
            
            # 清空并输入页码
            await input_locator.first.fill(str(target_page))
            print(f"[{self.name}] 已输入页码: {target_page}")
            
            button_locator = _build_locator(page, button_xpath)
            if not button_locator or await button_locator.count() == 0:
                print(f"[{self.name}] 未找到确定按钮")
                return False, 1
            
            await button_locator.first.click()
            
            # 等待页面加载
            import asyncio
            await asyncio.sleep(2)
            
            print(f"[{self.name}] ✓ 已通过控件跳转到第 {target_page} 页")
            return True, target_page
            
        except Exception as e:
            print(f"[{self.name}] 控件跳转失败: {e}")
            return False, 1


class SmartSkipStrategy(ResumeStrategy):
    """策略三: 首项检测与回溯 (兜底方案)
    
    从第 1 页开始，只检测第一条数据，快速跳过已爬页面。
    当检测到第一条新数据时，回退一页以确保完整性。
    """
    
    def __init__(
        self,
        collected_urls: set[str],
        detail_xpath: str | None = None,
        pagination_xpath: str | None = None,
    ):
        """初始化
        
        Args:
            collected_urls: 已收集的 URL 集合
            detail_xpath: 详情页链接的 xpath
            pagination_xpath: 下一页按钮的 xpath
        """
        self.collected_urls = collected_urls
        self.detail_xpath = detail_xpath
        self.pagination_xpath = pagination_xpath
    
    @property
    def name(self) -> str:
        return "首项检测回溯"
    
    async def _get_first_url(self, page: "Page") -> str | None:
        """获取列表页第一条数据的 URL"""
        if not self.detail_xpath:
            return None
        
        try:
            locator = _build_locator(page, self.detail_xpath)
            if not locator or await locator.count() == 0:
                return None
            
            href = await locator.first.get_attribute("href")
            if href:
                from urllib.parse import urljoin
                return urljoin(page.url, href)
            
            return None
        except Exception:
            return None
    
    async def _click_next_page(self, page: "Page") -> bool:
        """点击下一页"""
        if not self.pagination_xpath:
            return False
        
        try:
            locator = _build_locator(page, self.pagination_xpath)
            if not locator or await locator.count() == 0:
                return False
            
            # 检查是否禁用
            element = locator.first
            is_disabled = await element.get_attribute("disabled")
            class_attr = await element.get_attribute("class") or ""
            
            if is_disabled or "disabled" in class_attr:
                return False
            
            await element.click()
            
            import asyncio
            await asyncio.sleep(1)
            
            return True
        except Exception:
            return False
    
    async def _click_prev_page(self, page: "Page") -> bool:
        """点击上一页（用于回溯）"""
        # 尝试常见的上一页选择器
        prev_selectors = [
            "//a[contains(text(), '上一页')]",
            "//button[contains(text(), '上一页')]",
            "//*[contains(@class, 'prev')]//a",
            "//*[contains(@class, 'prev')]//button",
            "//li[contains(@class, 'ant-pagination-prev')]/button",
        ]
        
        for selector in prev_selectors:
            try:
                locator = page.locator(f"xpath={selector}")
                if await locator.count() > 0:
                    element = locator.first
                    if await element.is_visible():
                        await element.click()
                        import asyncio
                        await asyncio.sleep(1)
                        return True
            except Exception:
                continue
        
        return False
    
    async def try_resume(self, page: "Page", target_page: int) -> tuple[bool, int]:
        """通过首项检测快速跳过已爬页面"""
        if not self.detail_xpath or not self.pagination_xpath:
            print(f"[{self.name}] 缺少必要的 xpath 配置")
            return False, 1
        
        if not self.collected_urls:
            print(f"[{self.name}] 无已收集 URL，从第 1 页开始")
            return True, 1
        
        print(f"[{self.name}] 开始快速跳过已爬页面...")
        
        current_page = 1
        max_skip_pages = target_page + 10  # 防止无限循环
        
        while current_page < max_skip_pages:
            # 获取当前页第一条 URL
            first_url = await self._get_first_url(page)
            
            if not first_url:
                print(f"[{self.name}] 第 {current_page} 页无法获取首条 URL")
                break
            
            # 检查首条 URL 是否已存在
            if first_url in self.collected_urls:
                print(f"[{self.name}] 第 {current_page} 页首条已存在，快速跳过")
                
                # 点击下一页
                if not await self._click_next_page(page):
                    print(f"[{self.name}] 无法翻页，停止在第 {current_page} 页")
                    break
                
                current_page += 1
            else:
                # 首条不存在，说明到达断点附近
                print(f"[{self.name}] 第 {current_page} 页首条为新数据")
                
                # 回溯一页以确保完整性
                if current_page > 1:
                    print(f"[{self.name}] 回溯到第 {current_page - 1} 页以确保完整性")
                    if await self._click_prev_page(page):
                        current_page -= 1
                
                print(f"[{self.name}] ✓ 定位到第 {current_page} 页")
                return True, current_page
        
        print(f"[{self.name}] 快速跳过完成，当前第 {current_page} 页")
        return True, current_page


class ResumeCoordinator:
    """恢复协调器：按优先级尝试各策略"""
    
    def __init__(
        self,
        list_url: str,
        collected_urls: set[str],
        jump_widget_xpath: dict[str, str] | None = None,
        detail_xpath: str | None = None,
        pagination_xpath: str | None = None,
    ):
        """初始化
        
        Args:
            list_url: 列表页 URL
            collected_urls: 已收集的 URL 集合
            jump_widget_xpath: 跳转控件 xpath
            detail_xpath: 详情页链接 xpath
            pagination_xpath: 分页控件 xpath
        """
        self.strategies: list[ResumeStrategy] = [
            URLPatternStrategy(list_url),
            WidgetJumpStrategy(jump_widget_xpath),
            SmartSkipStrategy(collected_urls, detail_xpath, pagination_xpath),
        ]
    
    async def resume_to_page(self, page: "Page", target_page: int) -> int:
        """按优先级尝试恢复到目标页
        
        Args:
            page: Playwright Page 对象
            target_page: 目标页码
            
        Returns:
            实际恢复到的页码
        """
        print(f"\n[恢复协调器] 目标: 恢复到第 {target_page} 页")
        
        for i, strategy in enumerate(self.strategies, 1):
            print(f"\n[恢复协调器] 尝试策略 {i}/{len(self.strategies)}: {strategy.name}")
            
            success, actual_page = await strategy.try_resume(page, target_page)
            
            if success:
                print(f"[恢复协调器] ✓ 策略 '{strategy.name}' 成功，当前第 {actual_page} 页")
                return actual_page
            else:
                print(f"[恢复协调器] 策略 '{strategy.name}' 失败，尝试下一个")
        
        print(f"[恢复协调器] ⚠ 所有策略失败，从第 1 页开始")
        return 1

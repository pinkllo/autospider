"""
页面巡检员模块

负责管理异常处理器，并在页面导航时自动执行巡检。
"""
import asyncio
from typing import Optional
from playwright.async_api import Page
from loguru import logger

from .registry import get_handlers
from .handlers.base import BaseAnomalyHandler


class PageGuard:
    """
    页面巡检员。
    负责监听页面事件，在统一的时机对 Page 进行扫描。
    处理器列表从全局注册表自动获取，无需外部传入。
    """

    def __init__(self):
        self._is_handling = False  # 并发锁，确保同一时间只有一个处理器在工作
        self._lock = asyncio.Lock()

    async def run_inspection(self, page: Page):
        """
        执行统一巡检。
        从全局注册表获取处理器，按优先级处理第一个检测到的异常。
        """
        if self._is_handling:
            return

        async with self._lock:
            # 双重检查锁
            if self._is_handling:
                return

            # 从全局注册表获取已启用的处理器列表（按 priority 排序）
            handlers = get_handlers()
            
            for handler in handlers:
                try:
                    # 统一检查逻辑
                    if await handler.detect(page):
                        logger.warning(f"[PageGuard] 检测到异常状态: {handler.name}")
                        self._is_handling = True
                        
                        try:
                            # 发现问题，执行对应处理方法
                            await handler.handle(page)
                        finally:
                            # 无论成功与否，都重置处理状态
                            self._is_handling = False
                        
                        # 处理完一个主异常后，通常页面会刷新或跳转，跳出循环等待下一次巡检
                        break 
                except Exception as e:
                    self._is_handling = False
                    logger.error(f"[PageGuard] 处理器 {handler.name} 运行出错: {e}")

    def attach_to_page(self, page: Page):
        """
        将巡检员绑定到 Page 生命周期。
        主要监听导航完成事件，这是大部分异常（登录重定向、风控拦截）发生的时机。
        """
        # 监听主框架导航完成
        page.on("framenavigated", lambda frame: 
            asyncio.create_task(self.run_inspection(page)) 
            if frame == page.main_frame else None
        )
        
        # 也可以扩展监听其它事件，例如：
        # page.on("requestfailed", ...) 
        
        logger.debug("[PageGuard] 已挂载到当前页面")


# 为了向后兼容，保留从 guard 导入 BaseAnomalyHandler 的能力
__all__ = ["PageGuard", "BaseAnomalyHandler"]
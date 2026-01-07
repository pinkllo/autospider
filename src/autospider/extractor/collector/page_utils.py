"""页面操作工具函数"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


async def is_at_page_bottom(page: "Page", threshold: int = 50) -> bool:
    """检测页面是否已经滚动到底部
    
    Args:
        page: Playwright 页面对象
        threshold: 距离底部的阈值（像素），默认 50
        
    Returns:
        是否已经到达页面底部
    """
    try:
        result = await page.evaluate("""
            () => {
                const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                const scrollHeight = document.documentElement.scrollHeight;
                const clientHeight = window.innerHeight;
                return {
                    scrollTop: scrollTop,
                    scrollHeight: scrollHeight,
                    clientHeight: clientHeight,
                    distanceToBottom: scrollHeight - scrollTop - clientHeight
                };
            }
        """)
        return result["distanceToBottom"] <= threshold
    except Exception:
        return False


async def smart_scroll(page: "Page", distance: int = 500) -> bool:
    """智能滚动页面，如果已到达底部则不滚动
    
    Args:
        page: Playwright 页面对象
        distance: 滚动距离（像素）
        
    Returns:
        是否成功滚动（False 表示已到达底部，无法继续滚动）
    """
    if await is_at_page_bottom(page):
        return False
    
    await page.evaluate(f"window.scrollBy(0, {distance})")
    await asyncio.sleep(0.5)
    return True

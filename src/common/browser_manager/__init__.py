"""
browser_manager 模块

提供异步浏览器自动化管理，支持：
- 全局唯一 Browser 实例（单例模式）
- 自动异常检测与处理（登录、验证码、风控等）
- 反爬 Stealth 集成

基本用法：
    from common.browser_manager import get_browser_engine
    
    async def main():
        engine = await get_browser_engine()
        async with engine.page() as page:
            await page.goto("https://example.com")
            # 如果遇到登录页，会自动弹出人工接管横幅

扩展处理器：
    from common.browser_manager import register_handler, BaseAnomalyHandler
    
    class MyHandler(BaseAnomalyHandler):
        priority = 50
        @property
        def name(self): return "自定义处理器"
        async def detect(self, page): ...
        async def handle(self, page): ...
    
    register_handler(MyHandler())
"""

# 核心接口
from .engine import BrowserEngine, get_browser_engine

# 处理器注册接口
from .registry import (
    register_handler,
    get_handlers,
    enable_handler,
    disable_handler,
    get_registry,
    HandlerRegistry,
)

# 处理器基类
from .handlers.base import BaseAnomalyHandler

# 巡检员（通常不需要直接使用）
from .guard import PageGuard

__all__ = [
    # 核心
    "BrowserEngine",
    "get_browser_engine",
    # 注册表
    "register_handler",
    "get_handlers",
    "enable_handler",
    "disable_handler",
    "get_registry",
    "HandlerRegistry",
    # 扩展
    "BaseAnomalyHandler",
    "PageGuard",
]

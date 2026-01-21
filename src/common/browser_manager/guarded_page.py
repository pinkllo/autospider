"""
Page 代理类模块

提供 GuardedPage 类，包装原生 Playwright Page，
在所有可能触发导航的方法执行后自动等待异常处理完成。

业务代码使用此类代替原生 Page，完全无感地享受异常自动处理。
"""

import asyncio
from typing import Any, Optional, TYPE_CHECKING
from playwright.async_api import Page, Response, Download, FileChooser
from loguru import logger

if TYPE_CHECKING:
    from .guard import PageGuard


class GuardedPage:
    """
    Page 代理类，自动等待异常处理完成。
    
    核心机制：
    1. 拦截所有可能触发导航的方法（goto、click、reload 等）
    2. 在方法执行后自动等待 PageGuard 处理完成
    3. 透传其他属性和方法到原生 Page
    
    业务代码使用此类，无需额外操作即可实现异常自动阻塞等待。
    """
    
    def __init__(self, page: Page, guard: 'PageGuard'):
        """
        初始化 GuardedPage
        
        Args:
            page: 原生 Playwright Page 对象
            guard: 关联的 PageGuard 实例
        """
        self._page = page
        self._guard = guard
    
    # ==================== 导航类方法（需要等待 Guard） ====================
    
    async def goto(self, url: str, **kwargs) -> Optional[Response]:
        """
        导航到指定 URL
        
        执行后会自动等待 PageGuard 处理完成（如登录流程）
        """
        result = await self._page.goto(url, **kwargs)
        
        # 等待事件处理器有机会设置阻塞状态
        # 注意：这个延迟是必要的。framenavigated/domcontentloaded 事件是异步触发的，
        # 如果延迟太短，wait_until_idle() 会在事件处理器设置阻塞前就返回
        await asyncio.sleep(0.5)
        
        await self._wait_for_guard()
        return result
    
    async def reload(self, **kwargs) -> Optional[Response]:
        """
        刷新当前页面
        
        执行后会自动等待 PageGuard 处理完成
        """
        result = await self._page.reload(**kwargs)
        await self._wait_for_guard()
        return result
    
    async def go_back(self, **kwargs) -> Optional[Response]:
        """
        返回上一页
        
        执行后会自动等待 PageGuard 处理完成
        """
        result = await self._page.go_back(**kwargs)
        await self._wait_for_guard()
        return result
    
    async def go_forward(self, **kwargs) -> Optional[Response]:
        """
        前进到下一页
        
        执行后会自动等待 PageGuard 处理完成
        """
        result = await self._page.go_forward(**kwargs)
        await self._wait_for_guard()
        return result
    
    # ==================== 交互类方法（可能触发导航） ====================
    
    async def click(self, selector: str, **kwargs) -> None:
        """
        点击元素
        
        点击可能触发页面跳转，执行后会自动等待 PageGuard 处理完成
        """
        await self._page.click(selector, **kwargs)
        # 给一个短暂的时间让导航事件触发
        await asyncio.sleep(0.1)
        await self._wait_for_guard()
    
    async def dblclick(self, selector: str, **kwargs) -> None:
        """
        双击元素
        
        执行后会自动等待 PageGuard 处理完成
        """
        await self._page.dblclick(selector, **kwargs)
        await asyncio.sleep(0.1)
        await self._wait_for_guard()
    
    async def fill(self, selector: str, value: str, **kwargs) -> None:
        """
        填充表单字段
        
        普通填充不会触发导航，但为了一致性仍然检查
        """
        await self._page.fill(selector, value, **kwargs)
    
    async def press(self, selector: str, key: str, **kwargs) -> None:
        """
        按键操作（如 Enter 可能触发表单提交）
        
        执行后会自动等待 PageGuard 处理完成
        """
        await self._page.press(selector, key, **kwargs)
        # Enter 键等可能触发导航
        if key.lower() in ['enter', 'return']:
            await asyncio.sleep(0.1)
            await self._wait_for_guard()
    
    async def type(self, selector: str, text: str, **kwargs) -> None:
        """
        输入文本
        
        普通输入不会触发导航
        """
        await self._page.type(selector, text, **kwargs)
    
    # ==================== 等待类方法 ====================

    async def wait_for_new_page(self, predicate=None, timeout: float = 30.0) -> 'GuardedPage':
        """
        等待新页面打开并返回其 GuardedPage 包装
        
        Args:
            predicate: 用于筛选页面的函数，接收 Page 对象返回 bool
            timeout: 超时时间（秒）
            
        Returns:
            新页面的 GuardedPage 实例
        """
        # 注意: engine.py 中配置的 context.on("page") 已经确保了新页面会自动挂载 PageGuard
        # 这里只需要获取 Page 对象并包装即可
        new_page = await self._page.context.wait_for_event("page", predicate=predicate, timeout=timeout * 1000)
        
        # 等待 PageGuard 挂载完成（通过 Event Loop 让步）
        await asyncio.sleep(0.1)
        
        # 从 new_page 中获取可能已挂载的 Guard (虽然 GuardedPage 不需要显式传入 Guard 也能工作，
        # 但如果有 Guard 实例更好)
        # 目前 GuardedPage 构造函数需要 guard 实例，但在 Engine 中我们是直接 attach 到 Page 上的
        # 我们可以复用当前页面的 guard 实例，或者创建一个新的无关紧要，
        # 因为 Engine 已经在 new_page 上运行了一个 guard.run_inspection
        
        return GuardedPage(new_page, self._guard)
    
    async def wait_for_navigation(self, **kwargs) -> Optional[Response]:
        """
        等待导航完成
        
        执行后会自动等待 PageGuard 处理完成
        """
        result = await self._page.wait_for_navigation(**kwargs)
        await self._wait_for_guard()
        return result
    
    async def wait_for_url(self, url, **kwargs) -> None:
        """
        等待 URL 变化
        
        执行后会自动等待 PageGuard 处理完成
        """
        await self._page.wait_for_url(url, **kwargs)
        await self._wait_for_guard()
    
    async def wait_for_load_state(self, state: str = "load", **kwargs) -> None:
        """
        等待页面加载状态
        
        执行后会自动等待 PageGuard 处理完成
        """
        await self._page.wait_for_load_state(state, **kwargs)
        await self._wait_for_guard()
    
    # ==================== 内部方法 ====================
    
    async def _wait_for_guard(self) -> None:
        """
        等待 PageGuard 处理完成
        
        如果当前没有异常处理在进行，立即返回；
        否则阻塞直到处理完成。
        """
        await self._guard.wait_until_idle()
    
    # ==================== 属性代理 ====================
    
    @property
    def url(self) -> str:
        """当前页面 URL"""
        return self._page.url
    
    @property
    def content(self):
        """页面内容"""
        return self._page.content
    
    @property
    def title(self):
        """页面标题"""
        return self._page.title
    
    @property
    def context(self) -> 'GuardedContext':
        """浏览器上下文"""
        return GuardedContext(self._page.context, self._guard)
    
    @property
    def main_frame(self):
        """主框架"""
        return self._page.main_frame
    
    @property
    def key(self):
         return None
         
    @property
    def frames(self):
        """所有框架"""
        return self._page.frames
        
    @property
    def keyboard(self) -> 'GuardedKeyboard':
        """键盘对象代理"""
        return GuardedKeyboard(self._page.keyboard, self._guard)

    
    # ==================== 透传其他属性和方法 ====================
    
    def __getattr__(self, name: str) -> Any:
        """
        透传未定义的属性和方法到原生 Page
        
        这样可以确保所有 Page 的功能都可用，
        即使没有显式定义也能正常工作。
        """
        return getattr(self._page, name)
    
    # ==================== 获取原生 Page ====================
    
    def unwrap(self) -> Page:
        """
        获取原生 Page 对象
        
        在某些需要原生 Page 的场景下使用。
        注意：使用原生 Page 将绕过 Guard 等待机制。
        """
        return self._page


class GuardedContext:
    """
    BrowserContext 代理类，确保获取的 Page 都是 GuardedPage。
    """
    
    def __init__(self, context: Any, guard: 'PageGuard'):
        self._context = context
        self._guard = guard

    @property
    def pages(self) -> list['GuardedPage']:
        """获取所有页面，并包装为 GuardedPage"""
        return [GuardedPage(page, self._guard) for page in self._context.pages]

    async def wait_for_event(self, event: str, predicate=None, timeout: float = 30000) -> Any:
        """
        等待事件。如果事件是 'page'，返回 GuardedPage。
        """
        result = await self._context.wait_for_event(event, predicate=predicate, timeout=timeout)
        if event == "page" and isinstance(result, Page):
            # 等待 PageGuard 挂载完成
            await asyncio.sleep(0.1)
            return GuardedPage(result, self._guard)
        return result

    async def new_page(self, **kwargs) -> 'GuardedPage':
        """创建新页面并返回 GuardedPage"""
        page = await self._context.new_page(**kwargs)
        # 等待 PageGuard 挂载完成
        await asyncio.sleep(0.1)
        return GuardedPage(page, self._guard)

    def __getattr__(self, name: str) -> Any:
        """透传其他属性和方法"""
        return getattr(self._context, name)


class GuardedKeyboard:
    """
    Keyboard 代理类，仅拦截 press 方法。
    """
    
    def __init__(self, keyboard: Any, guard: 'PageGuard'):
        self._keyboard = keyboard
        self._guard = guard

    async def press(self, key: str, **kwargs) -> None:
        """
        按键操作。
        执行后会自动等待 PageGuard 处理完成（仅限 Enter/Return）。
        """
        await self._keyboard.press(key, **kwargs)
        
        # 仅在按下 Enter 为确认键时检查
        if key.lower() in ['enter', 'return']:
            # 给一个短暂的时间让导航事件触发
            await asyncio.sleep(0.1)
            await self._guard.wait_until_idle()

    def __getattr__(self, name: str) -> Any:
        """透传 type, down, up, insert_text 等其他方法"""
        return getattr(self._keyboard, name)

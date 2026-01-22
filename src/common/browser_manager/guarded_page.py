"""
Page 代理类模块（动态代理版本）

提供 GuardedPage 类，包装原生 Playwright Page，
在所有可能触发导航的方法执行后自动等待异常处理完成。

使用动态代理模式，通过 __getattr__ 自动拦截方法调用，
大幅减少样板代码，同时保持完整的 Guard 保护机制。
"""

import asyncio
import functools
from typing import Any, Optional, TYPE_CHECKING, FrozenSet
from playwright.async_api import Page, Response
from loguru import logger

if TYPE_CHECKING:
    from .guard import PageGuard


class GuardedPage:
    """
    Page 动态代理类，自动等待异常处理完成。
    
    核心机制：
    1. 通过 __getattr__ 自动拦截所有方法调用
    2. 根据方法类型（导航/交互/定位器）决定是否注入 Guard 等待逻辑
    3. 保持与原生 Page 完全兼容的接口
    
    业务代码使用此类，无需额外操作即可实现异常自动阻塞等待。
    """
    
    # ==================== 方法分类配置 ====================
    
    # 返回 GuardedLocator 的工厂方法
    _LOCATOR_FACTORIES: FrozenSet[str] = frozenset({
        'locator', 'get_by_role', 'get_by_text', 'get_by_label',
        'get_by_placeholder', 'get_by_alt_text', 'get_by_title', 'get_by_test_id'
    })
    
    # 导航类方法：执行后需要等待 Guard（较长延迟）
    _NAVIGATION_METHODS: FrozenSet[str] = frozenset({
        'goto', 'reload', 'go_back', 'go_forward',
        'wait_for_navigation', 'wait_for_url', 'wait_for_load_state'
    })
    
    # 交互类方法：可能触发导航，执行后需要等待 Guard
    _INTERACTION_METHODS: FrozenSet[str] = frozenset({
        'click', 'dblclick', 'tap', 'check', 'uncheck', 'select_option'
    })
    
    # 需要特殊处理的按键方法（仅 Enter/Return 触发等待）
    _PRESS_METHODS: FrozenSet[str] = frozenset({'press'})
    
    def __init__(self, page: Page, guard: 'PageGuard'):
        """
        初始化 GuardedPage
        
        Args:
            page: 原生 Playwright Page 对象
            guard: 关联的 PageGuard 实例
        """
        # 使用 object.__setattr__ 避免触发 __getattr__
        object.__setattr__(self, '_page', page)
        object.__setattr__(self, '_guard', guard)
    
    # ==================== 动态代理核心 ====================
    
    def __getattr__(self, name: str) -> Any:
        """
        动态代理：根据方法类型自动注入 Guard 等待逻辑
        
        处理逻辑：
        1. 定位器工厂方法 → 返回 GuardedLocator
        2. 导航类方法 → 包装并等待 Guard（0.5s 延迟）
        3. 交互类方法 → 包装并等待 Guard（0.1s 延迟）
        4. 按键方法 → 仅 Enter/Return 触发等待
        5. 其他方法 → 直接透传
        """
        attr = getattr(self._page, name)
        
        # 如果不是可调用对象，直接返回
        if not callable(attr):
            return attr
        
        # 定位器工厂方法：返回 GuardedLocator
        if name in self._LOCATOR_FACTORIES:
            @functools.wraps(attr)
            def locator_factory(*args, **kwargs):
                return GuardedLocator(attr(*args, **kwargs), self._guard)
            return locator_factory
        
        # 导航类方法：需要较长延迟等待事件触发
        if name in self._NAVIGATION_METHODS:
            @functools.wraps(attr)
            async def navigation_wrapper(*args, **kwargs):
                result = await attr(*args, **kwargs)
                # 导航操作需要较长延迟，确保 framenavigated 事件有机会触发
                await asyncio.sleep(0.5)
                await self._guard.wait_until_idle()
                return result
            return navigation_wrapper
        
        # 交互类方法：可能触发导航
        if name in self._INTERACTION_METHODS:
            @functools.wraps(attr)
            async def interaction_wrapper(*args, **kwargs):
                result = await attr(*args, **kwargs)
                # 交互操作延迟较短
                await asyncio.sleep(0.1)
                await self._guard.wait_until_idle()
                return result
            return interaction_wrapper
        
        # 按键方法：仅 Enter/Return 触发等待
        if name in self._PRESS_METHODS:
            @functools.wraps(attr)
            async def press_wrapper(selector: str, key: str, *args, **kwargs):
                await attr(selector, key, *args, **kwargs)
                # 仅 Enter/Return 可能触发表单提交导航
                if key.lower() in ('enter', 'return'):
                    await asyncio.sleep(0.1)
                    await self._guard.wait_until_idle()
            return press_wrapper
        
        # 其他方法直接透传
        return attr
    
    # ==================== 需要手动定义的特殊属性 ====================
    
    @property
    def keyboard(self) -> 'GuardedKeyboard':
        """键盘对象代理，拦截 press 操作"""
        return GuardedKeyboard(self._page.keyboard, self._guard)
    
    @property
    def context(self) -> 'GuardedContext':
        """浏览器上下文代理，确保获取的 Page 都是 GuardedPage"""
        return GuardedContext(self._page.context, self._guard)
    
    @property
    def url(self) -> str:
        """当前页面 URL"""
        return self._page.url
    
    @property
    def frames(self):
        """所有框架"""
        return self._page.frames
    
    @property
    def main_frame(self):
        """主框架"""
        return self._page.main_frame
    
    # ==================== 特殊方法 ====================
    
    async def wait_for_new_page(self, predicate=None, timeout: float = 30.0) -> 'GuardedPage':
        """
        等待新页面打开并返回其 GuardedPage 包装
        
        Args:
            predicate: 用于筛选页面的函数，接收 Page 对象返回 bool
            timeout: 超时时间（秒）
            
        Returns:
            新页面的 GuardedPage 实例
        """
        new_page = await self._page.context.wait_for_event(
            "page", predicate=predicate, timeout=timeout * 1000
        )
        # 等待 PageGuard 挂载完成
        await asyncio.sleep(0.1)
        return GuardedPage(new_page, self._guard)
    
    def unwrap(self) -> Page:
        """
        获取原生 Page 对象
        
        注意：使用原生 Page 将绕过 Guard 等待机制。
        """
        return self._page


class GuardedContext:
    """
    BrowserContext 动态代理类，确保获取的 Page 都是 GuardedPage。
    """
    
    def __init__(self, context: Any, guard: 'PageGuard'):
        object.__setattr__(self, '_context', context)
        object.__setattr__(self, '_guard', guard)

    @property
    def pages(self) -> list['GuardedPage']:
        """获取所有页面，并包装为 GuardedPage"""
        return [GuardedPage(page, self._guard) for page in self._context.pages]

    async def wait_for_event(self, event: str, predicate=None, timeout: float = 30000) -> Any:
        """等待事件。如果事件是 'page'，返回 GuardedPage。"""
        result = await self._context.wait_for_event(event, predicate=predicate, timeout=timeout)
        if event == "page":
            await asyncio.sleep(0.1)
            return GuardedPage(result, self._guard)
        return result

    async def new_page(self, **kwargs) -> 'GuardedPage':
        """创建新页面并返回 GuardedPage"""
        page = await self._context.new_page(**kwargs)
        await asyncio.sleep(0.1)
        return GuardedPage(page, self._guard)

    def __getattr__(self, name: str) -> Any:
        """透传其他属性和方法"""
        return getattr(self._context, name)


class GuardedKeyboard:
    """
    Keyboard 动态代理类，仅拦截 press 方法。
    """
    
    def __init__(self, keyboard: Any, guard: 'PageGuard'):
        object.__setattr__(self, '_keyboard', keyboard)
        object.__setattr__(self, '_guard', guard)

    async def press(self, key: str, **kwargs) -> None:
        """
        按键操作。
        执行后自动等待 PageGuard 处理完成（仅限 Enter/Return）。
        """
        await self._keyboard.press(key, **kwargs)
        if key.lower() in ('enter', 'return'):
            await asyncio.sleep(0.1)
            await self._guard.wait_until_idle()

    def __getattr__(self, name: str) -> Any:
        """透传 type, down, up, insert_text 等其他方法"""
        return getattr(self._keyboard, name)


class GuardedLocator:
    """
    Locator 动态代理类，拦截交互操作。
    """
    
    # 返回新 GuardedLocator 的链式方法
    _CHAIN_METHODS: FrozenSet[str] = frozenset({
        'locator', 'nth', 'filter', 'and_', 'or_',
        'get_by_role', 'get_by_text', 'get_by_label',
        'get_by_placeholder', 'get_by_alt_text', 'get_by_title', 'get_by_test_id'
    })
    
    # 返回新 GuardedLocator 的链式属性
    _CHAIN_PROPERTIES: FrozenSet[str] = frozenset({'first', 'last'})
    
    # 需要后置等待的交互方法
    _INTERACTION_METHODS: FrozenSet[str] = frozenset({
        'click', 'dblclick', 'tap', 'check', 'uncheck', 
        'select_option', 'set_checked'
    })
    
    def __init__(self, locator: Any, guard: 'PageGuard'):
        object.__setattr__(self, '_locator', locator)
        object.__setattr__(self, '_guard', guard)
    
    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._locator, name)
        
        # 链式属性：返回 GuardedLocator
        if name in self._CHAIN_PROPERTIES:
            return GuardedLocator(attr, self._guard)
        
        # 链式方法：返回 GuardedLocator
        if name in self._CHAIN_METHODS:
            @functools.wraps(attr)
            def chain_wrapper(*args, **kwargs):
                # 处理传入的 GuardedLocator 参数（如 and_, or_）
                processed_args = []
                for arg in args:
                    if isinstance(arg, GuardedLocator):
                        processed_args.append(arg._locator)
                    else:
                        processed_args.append(arg)
                return GuardedLocator(attr(*processed_args, **kwargs), self._guard)
            return chain_wrapper
        
        # 交互方法：需要后置等待
        if name in self._INTERACTION_METHODS:
            @functools.wraps(attr)
            async def interaction_wrapper(*args, **kwargs):
                result = await attr(*args, **kwargs)
                await asyncio.sleep(0.1)
                await self._guard.wait_until_idle()
                return result
            return interaction_wrapper
        
        # press 方法：仅 Enter/Return 触发等待
        if name == 'press':
            @functools.wraps(attr)
            async def press_wrapper(key: str, *args, **kwargs):
                await attr(key, *args, **kwargs)
                if key.lower() in ('enter', 'return'):
                    await asyncio.sleep(0.1)
                    await self._guard.wait_until_idle()
            return press_wrapper
        
        # 其他方法/属性直接透传
        return attr

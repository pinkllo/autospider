"""
Page 代理类模块（__getattribute__ 全方法拦截版）

使用 __getattribute__ 实现全方法拦截，
所有异步方法执行前后自动等待 Guard 空闲，
让业务代码完全无感知地获得异常保护。

核心优势：
1. 无需手动维护方法列表
2. 自动识别所有异步方法（包括 evaluate、screenshot 等）
3. 业务代码完全无感知
"""

import asyncio
import functools
import inspect
from typing import Any, Optional, TYPE_CHECKING, FrozenSet
from playwright.async_api import Page, Response
from loguru import logger

if TYPE_CHECKING:
    from .guard import PageGuard


class GuardedPage:
    """
    Page 动态代理类，使用 __getattribute__ 实现全方法拦截。
    
    核心机制：
    1. 拦截所有属性访问
    2. 对异步方法自动注入 Guard 等待逻辑
    3. 执行前后都会等待 Guard 空闲
    
    业务代码使用此类，无需额外操作即可实现异常自动阻塞等待。
    """
    
    # 需要跳过等待的属性/方法名（同步属性、内部属性等）
    _SKIP_WAIT: FrozenSet[str] = frozenset({
        # 属性
        'url', 'frames', 'main_frame', 
        'is_closed', 'video', 'workers', 'request', 'viewportSize',
        # 内部方法
        'unwrap', '_page', '_guard', '_SKIP_WAIT', '_LOCATOR_FACTORIES',
        # 事件相关（同步）
        'on', 'once', 'remove_listener', 'set_default_timeout', 'set_default_navigation_timeout',
    })
    
    # 返回 GuardedLocator 的工厂方法
    _LOCATOR_FACTORIES: FrozenSet[str] = frozenset({
        'locator', 'get_by_role', 'get_by_text', 'get_by_label',
        'get_by_placeholder', 'get_by_alt_text', 'get_by_title', 'get_by_test_id',
        'frame_locator',
    })
    
    def __init__(self, page: Page, guard: 'PageGuard'):
        """
        初始化 GuardedPage
        
        Args:
            page: 原生 Playwright Page 对象
            guard: 关联的 PageGuard 实例
        """
        # 使用 object.__setattr__ 避免触发 __getattribute__
        object.__setattr__(self, '_page', page)
        object.__setattr__(self, '_guard', guard)
    
    def __getattribute__(self, name: str) -> Any:
        """
        全方法拦截器
        
        处理逻辑：
        1. 内部属性（以 _ 开头）→ 直接返回
        2. 跳过列表中的属性 → 直接透传
        3. 定位器工厂方法 → 返回 GuardedLocator
        4. 异步方法 → 包装并注入等待逻辑
        5. 其他 → 直接透传
        """
        # 内部属性直接返回
        if name.startswith('_') or name in ('unwrap',):
            return object.__getattribute__(self, name)
        
        # 获取私有属性
        page = object.__getattribute__(self, '_page')
        guard = object.__getattribute__(self, '_guard')
        skip_wait = object.__getattribute__(self, '_SKIP_WAIT')
        locator_factories = object.__getattribute__(self, '_LOCATOR_FACTORIES')
        
        # 特殊处理 context 属性 - 返回 GuardedContext
        if name == 'context':
            return GuardedContext(page.context, guard)
        
        # 特殊处理 keyboard 属性 - 返回 GuardedKeyboard
        if name == 'keyboard':
            return GuardedKeyboard(page.keyboard, guard)
        
        # 获取原生属性
        try:
            attr = getattr(page, name)
        except AttributeError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        
        # 跳过不需要等待的属性
        if name in skip_wait:
            return attr
        
        # 定位器工厂方法：返回 GuardedLocator
        if name in locator_factories:
            @functools.wraps(attr)
            def locator_factory(*args, **kwargs):
                return GuardedLocator(attr(*args, **kwargs), guard)
            return locator_factory
        
        # 如果是协程函数，包装并注入等待逻辑
        if asyncio.iscoroutinefunction(attr):
            @functools.wraps(attr)
            async def guarded_wrapper(*args, **kwargs):
                # 执行前等待 Guard 空闲
                await guard.wait_until_idle()
                
                # 执行原方法
                result = await attr(*args, **kwargs)
                
                # 执行后给事件一点时间触发，然后再次等待
                await asyncio.sleep(0.1)
                await guard.wait_until_idle()
                
                return result
            return guarded_wrapper
        
        # 其他属性/方法直接透传
        return attr
    
    def __setattr__(self, name: str, value: Any) -> None:
        """属性设置直接透传到原生 Page"""
        if name.startswith('_'):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, '_page'), name, value)
    
    # ==================== 需要手动定义的特殊方法 ====================
    
    @property
    def url(self) -> str:
        """当前页面 URL"""
        return object.__getattribute__(self, '_page').url
    
    @property
    def content(self):
        """页面内容（异步方法，需特殊处理）"""
        return object.__getattribute__(self, '_page').content
    
    def is_closed(self) -> bool:
        """页面是否已关闭"""
        return object.__getattribute__(self, '_page').is_closed()
    
    def unwrap(self) -> Page:
        """
        获取原生 Page 对象
        
        注意：使用原生 Page 将绕过 Guard 等待机制。
        在某些需要原生 Page 的场景下使用。
        """
        return object.__getattribute__(self, '_page')


class GuardedContext:
    """
    BrowserContext 代理类，确保所有途径获取的 Page 都是 GuardedPage。
    """
    
    def __init__(self, context: Any, guard: 'PageGuard'):
        object.__setattr__(self, '_context', context)
        object.__setattr__(self, '_guard', guard)

    def _wrap_page(self, page: Any) -> Any:
        # 如果不是 Page 对象（可能是 None 或其他），直接返回
        if not isinstance(page, Page):
            return page
            
        # 如果已经是 GuardedPage，直接返回
        if isinstance(page, GuardedPage):
            return page

        # 检查是否已挂载 Guard
        guard = object.__getattribute__(self, '_guard')
        if not getattr(page, "_guard_attached", False):
             # 兜底挂载：防止 engine 层遗漏
             guard.attach_to_page(page)
             # 立即在后台触发一次检查
             asyncio.create_task(guard.run_inspection(page))
        
        return GuardedPage(page, guard)

    @property
    def pages(self) -> list['GuardedPage']:
        """获取所有页面，并包装为 GuardedPage"""
        context = object.__getattribute__(self, '_context')
        return [self._wrap_page(page) for page in context.pages]

    async def wait_for_event(self, event: str, predicate=None, timeout: float = 30000) -> Any:
        """等待事件。如果事件是 'page'，返回 GuardedPage。"""
        context = object.__getattribute__(self, '_context')
        result = await context.wait_for_event(event, predicate=predicate, timeout=timeout)
        
        if event == "page":
            await asyncio.sleep(0.1)
            return self._wrap_page(result)
        return result

    async def new_page(self, **kwargs) -> 'GuardedPage':
        """创建新页面并返回 GuardedPage"""
        context = object.__getattribute__(self, '_context')
        page = await context.new_page(**kwargs)
        await asyncio.sleep(0.1)
        return self._wrap_page(page)

    def expect_page(self, predicate=None, timeout: float = 30000) -> 'GuardedEventContextManager':
        """
        拦截 expect_page，确保返回的 Future value 是 GuardedPage。
        """
        context = object.__getattribute__(self, '_context')
        raw_manager = context.expect_page(predicate=predicate, timeout=timeout)
        return GuardedEventContextManager(raw_manager, self._wrap_page)

    def __getattr__(self, name: str) -> Any:
        """透传其他属性和方法"""
        return getattr(object.__getattribute__(self, '_context'), name)


class GuardedEventContextManager:
    """
    包装 Playwright 的 EventContextManager，拦截其 value 属性。
    """
    def __init__(self, raw_manager: Any, wrap_fn: Any):
        self._raw_manager = raw_manager
        self._wrap_fn = wrap_fn

    async def __aenter__(self):
        # 进入上下文管理器，获取原生 EventInfo
        # 这里返回的是 self，以便我们拦截 value 属性
        self._event_info = await self._raw_manager.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self._raw_manager.__aexit__(exc_type, exc_val, exc_tb)

    @property
    def value(self):
        """
        拦截 value 属性。
        原生 implementation 返回的是一个 Awaitable[Page]。
        我们需要包装这个 Awaitable，在它 resolve 后 wrap 结果。
        """
        raw_future = self._event_info.value
        
        async def wrapped_future():
            try:
                page = await raw_future
                # 给一点时间让事件传播
                await asyncio.sleep(0.1)
                return self._wrap_fn(page)
            except Exception as e:
                raise e
                
        return wrapped_future()


class GuardedKeyboard:
    """
    Keyboard 代理类，拦截 press 方法以触发 Guard 等待。
    """
    
    def __init__(self, keyboard: Any, guard: 'PageGuard'):
        object.__setattr__(self, '_keyboard', keyboard)
        object.__setattr__(self, '_guard', guard)

    async def press(self, key: str, **kwargs) -> None:
        """
        按键操作。
        执行后自动等待 PageGuard 处理完成（仅限 Enter/Return）。
        """
        keyboard = object.__getattribute__(self, '_keyboard')
        guard = object.__getattribute__(self, '_guard')
        
        await keyboard.press(key, **kwargs)
        if key.lower() in ('enter', 'return'):
            await asyncio.sleep(0.1)
            await guard.wait_until_idle()

    def __getattr__(self, name: str) -> Any:
        """透传 type, down, up, insert_text 等其他方法"""
        return getattr(object.__getattribute__(self, '_keyboard'), name)


class GuardedLocator:
    """
    Locator 代理类，使用 __getattribute__ 拦截所有交互操作。
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
    
    def __getattribute__(self, name: str) -> Any:
        # 内部属性直接返回
        if name.startswith('_'):
            return object.__getattribute__(self, name)
        
        locator = object.__getattribute__(self, '_locator')
        guard = object.__getattribute__(self, '_guard')
        chain_methods = object.__getattribute__(self, '_CHAIN_METHODS')
        chain_properties = object.__getattribute__(self, '_CHAIN_PROPERTIES')
        interaction_methods = object.__getattribute__(self, '_INTERACTION_METHODS')
        
        try:
            attr = getattr(locator, name)
        except AttributeError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        
        # 链式属性：返回 GuardedLocator
        if name in chain_properties:
            return GuardedLocator(attr, guard)
        
        # 链式方法：返回 GuardedLocator
        if name in chain_methods:
            @functools.wraps(attr)
            def chain_wrapper(*args, **kwargs):
                # 处理传入的 GuardedLocator 参数（如 and_, or_）
                processed_args = []
                for arg in args:
                    if isinstance(arg, GuardedLocator):
                        processed_args.append(object.__getattribute__(arg, '_locator'))
                    else:
                        processed_args.append(arg)
                return GuardedLocator(attr(*processed_args, **kwargs), guard)
            return chain_wrapper
        
        # 交互方法：需要后置等待
        if name in interaction_methods:
            @functools.wraps(attr)
            async def interaction_wrapper(*args, **kwargs):
                await guard.wait_until_idle()  # 执行前等待
                result = await attr(*args, **kwargs)
                await asyncio.sleep(0.1)
                await guard.wait_until_idle()  # 执行后等待
                return result
            return interaction_wrapper
        
        # press 方法：仅 Enter/Return 触发等待
        if name == 'press':
            @functools.wraps(attr)
            async def press_wrapper(key: str, *args, **kwargs):
                await guard.wait_until_idle()
                await attr(key, *args, **kwargs)
                if key.lower() in ('enter', 'return'):
                    await asyncio.sleep(0.1)
                    await guard.wait_until_idle()
            return press_wrapper
        
        # 其他异步方法也包装
        if asyncio.iscoroutinefunction(attr):
            @functools.wraps(attr)
            async def async_wrapper(*args, **kwargs):
                await guard.wait_until_idle()
                return await attr(*args, **kwargs)
            return async_wrapper
        
        # 其他方法/属性直接透传
        return attr

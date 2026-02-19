"""
页面巡检员模块

负责管理异常处理器，并在页面导航时自动执行巡检。
支持业务代码无感等待机制。
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
    
    核心功能：
    1. 监听页面事件，在导航完成时自动扫描异常
    2. 处理器列表从全局注册表自动获取
    3. 提供 wait_until_idle() 方法，让业务代码可以等待处理完成
    
    与 GuardedPage 配合使用，实现业务代码无感的异常处理。
    """

    def __init__(self):
        self._is_handling = False  # 标记是否正在处理异常
        self._lock = asyncio.Lock()  # 并发锁，确保同一时间只有一个处理器在工作
        self._poll_tasks: dict[int, asyncio.Task] = {}
        self._poll_interval_s = 1.0
        
        # 空闲事件：用于阻塞等待处理完成
        # set() = 空闲状态，clear() = 处理中状态
        self._idle_event = asyncio.Event()
        self._idle_event.set()  # 初始为空闲状态

    async def run_inspection(self, page: Page):
        """
        执行统一巡检。
        
        从全局注册表获取处理器，按优先级处理第一个检测到的异常。
        检测到异常时会阻塞 wait_until_idle() 的等待者。
        """
        if self._is_handling:
            logger.debug("[PageGuard] 跳过巡检：已在处理中")
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
                        
                        # 设置为处理中状态
                        self._is_handling = True
                        self._idle_event.clear()  # 阻塞所有等待者
                        logger.debug("[PageGuard] _idle_event.clear() - 开始阻塞")
                        
                        try:
                            # 发现问题，执行对应处理方法
                            await handler.handle(page)
                            # 统一后置动作：异常处理后刷新当前 context 的全部页面，
                            # 让共享风控状态在各标签页尽快同步生效。
                            await self._refresh_context_pages(page, source_handler=handler.name)
                        finally:
                            # 无论成功与否，都重置处理状态并释放等待者
                            self._is_handling = False
                            self._idle_event.set()  # 释放所有等待者
                            logger.debug("[PageGuard] _idle_event.set() - 解除阻塞")
                        
                        # 处理完一个主异常后，通常页面会刷新或跳转，跳出循环等待下一次巡检
                        break 
                except Exception as e:
                    # 出错时也要确保状态正确重置
                    self._is_handling = False
                    self._idle_event.set()
                    logger.error(f"[PageGuard] 处理器 {handler.name} 运行出错: {e}")

    async def _refresh_context_pages(self, page: Page, source_handler: str) -> None:
        """刷新当前 BrowserContext 内的所有页面。"""
        try:
            pages = list(page.context.pages)
        except Exception as e:
            logger.debug(f"[PageGuard] 获取 context.pages 失败（忽略）: {e}")
            return

        if not pages:
            return

        logger.info(
            f"[PageGuard] 异常处理完成（{source_handler}），开始刷新当前 context 全部页面: {len(pages)} 个"
        )
        for p in pages:
            try:
                if p.is_closed():
                    continue
                await p.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.debug(f"[PageGuard] 刷新页面失败（忽略）: {e}")

    async def wait_until_idle(self) -> None:
        """
        等待巡检处理完成。
        
        如果当前没有异常处理在进行，立即返回；
        否则阻塞直到处理完成。
        
        此方法由 GuardedPage 在导航操作后调用，实现业务代码无感等待。
        """
        await self._idle_event.wait()

    def attach_to_page(self, page: Page):
        """
        将巡检员绑定到 Page 生命周期。
        
        监听的事件：
        - framenavigated: 主框架导航完成 + 登录相关 iframe 导航
        - domcontentloaded: DOM 加载完成（捕获弹窗式登录）
        """
        # 避免重复绑定同一个页面
        try:
            if getattr(page, "_guard_attached", False):
                return
        except Exception:
            pass

        # 登录相关关键词（用于判断 iframe 是否需要触发检测）
        login_keywords = ["login", "passport", "signin", "member", "auth"]
        
        def should_inspect(frame) -> bool:
            """判断是否需要触发巡检"""
            # 主框架始终检测
            if frame == page.main_frame:
                return True
            
            # 检查 iframe URL 是否包含登录关键词
            frame_url = frame.url.lower()
            return any(k in frame_url for k in login_keywords)
        
        # 标记绑定状态，供外部兜底逻辑使用
        try:
            setattr(page, "_page_guard", self)
            setattr(page, "_guard_attached", True)
        except Exception:
            pass

        # 监听 frame 导航（主框架 + 登录相关 iframe）
        page.on("framenavigated", lambda frame: 
            asyncio.create_task(self.run_inspection(page)) 
            if should_inspect(frame) else None
        )
        
        # 监听 DOM 内容加载（捕获弹窗式登录）
        page.on("domcontentloaded", lambda: 
            asyncio.create_task(self.run_inspection(page))
        )

        # 启动轻量轮询，覆盖“无导航触发的风控弹窗（如滑块）”
        self._ensure_polling(page)
        
        logger.debug("[PageGuard] 已挂载到当前页面（支持 iframe 检测）")

    def _ensure_polling(self, page: Page) -> None:
        """确保页面巡检轮询任务已启动。"""
        page_id = id(page)
        task = self._poll_tasks.get(page_id)
        if task and not task.done():
            return
        self._poll_tasks[page_id] = asyncio.create_task(self._poll_page(page))

    async def _poll_page(self, page: Page) -> None:
        """页面巡检轮询：用于检测无导航触发的异常。"""
        page_id = id(page)
        try:
            while True:
                try:
                    if page.is_closed():
                        break
                except Exception:
                    break

                try:
                    await self.run_inspection(page)
                except Exception as e:
                    logger.debug(f"[PageGuard] 轮询巡检异常（忽略）: {e}")

                await asyncio.sleep(self._poll_interval_s)
        finally:
            self._poll_tasks.pop(page_id, None)


# ==================== 全局工具函数 ====================


async def ensure_guard_idle(page: "Page") -> None:
    """
    全局工具函数：确保 Guard 空闲
    
    任何需要与页面交互的代码都可以调用此函数，
    它会自动检测页面是否有 Guard，并等待其空闲。
    
    使用场景：
    - 外部模块直接拿到原生 Page 时
    - 在 GuardedPage 无法覆盖的场景下
    
    用法：
        from browser_manager.guard import ensure_guard_idle
        
        await ensure_guard_idle(page)
        # 现在可以安全地操作页面了
    """
    try:
        from .guarded_page import GuardedPage
        
        # 如果是 GuardedPage，直接调用其 Guard
        if isinstance(page, GuardedPage):
            guard = object.__getattribute__(page, '_guard')
            await guard.wait_until_idle()
            return
        
        # 如果是原生 Page，尝试获取挂载的 Guard
        guard = getattr(page, '_page_guard', None)
        if guard is not None:
            await guard.wait_until_idle()
    except Exception as e:
        logger.debug(f"[ensure_guard_idle] 等待失败（可忽略）: {e}")


# 为了向后兼容，保留从 guard 导入 BaseAnomalyHandler 的能力
__all__ = ["PageGuard", "BaseAnomalyHandler", "ensure_guard_idle"]

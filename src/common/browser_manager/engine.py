"""
异步浏览器引擎

提供全局唯一的 Browser 实例管理，集成 PageGuard 自动监控机制。
所有页面自动启用异常拦截，业务代码无需手动配置处理器。
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator, Dict, List, Literal, Any
from playwright.async_api import async_playwright, Browser, Playwright, Page
from playwright_stealth import Stealth
from loguru import logger

from .guard import PageGuard

# 导入 handlers 包触发所有内置处理器的自动注册


class BrowserEngine:
    """
    异步浏览器引擎：
    1. 管理全局唯一的 Browser 实例。
    2. 集成 PageGuard 巡检机制，实现业务无感的异常拦截。
    3. 所有通过 page() 获取的页面自动启用监控。
    """

    def __init__(
        self,
        default_headless: bool = True,
        default_viewport: Optional[Dict[str, int]] = None,
        default_user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        default_launch_args: Optional[List[str]] = None,
        default_browser_type: Literal["chromium", "firefox", "webkit"] = "chromium",
        max_retries: int = 2,
        default_timeout: int = 30000,
    ):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._stealth_context: Optional[Any] = None
        self._current_headless: bool = default_headless
        self._lock = asyncio.Lock()
        self._owner_loop: Optional[asyncio.AbstractEventLoop] = None

        self.default_headless = default_headless
        self.default_viewport = default_viewport or {"width": 1920, "height": 1080}
        self.default_user_agent = default_user_agent
        self.default_browser_type = default_browser_type
        self.max_retries = max_retries
        self.default_timeout = default_timeout

        self.default_launch_args = default_launch_args or [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-extensions",
            "--no-first-run",
        ]

    async def _ensure_browser(self, headless: bool):
        """
        确保全局 Browser 实例存活且可用

        此方法是浏览器生命周期管理的核心，负责：
        1. 检测浏览器是否需要（重新）启动
        2. 处理 Event Loop 切换场景（如在不同协程环境中调用）
        3. 处理 headless 模式切换
        4. 带重试机制的浏览器启动

        Args:
            headless: 是否以无头模式运行浏览器

        Note:
            - 使用 asyncio.Lock 保证线程安全，防止并发创建多个浏览器实例
            - 集成 playwright_stealth 绕过反爬虫检测
        """
        # 获取当前运行的事件循环，用于检测是否发生 Loop 切换
        current_loop = asyncio.get_running_loop()

        # 使用锁保护，确保同一时间只有一个协程能操作浏览器实例
        async with self._lock:
            should_restart = False

            # === 判断是否需要重启浏览器的三个条件 ===

            # 条件1: Event Loop 发生变化（例如在新线程中调用）
            # 这种情况下旧的浏览器实例无法在新 Loop 中使用，必须重建
            if self._browser and self._owner_loop and self._owner_loop != current_loop:
                logger.warning("Event Loop changed. Restarting browser...")
                should_restart = True

            # 条件2: 浏览器实例不存在或已断开连接
            # 可能是首次启动，或浏览器意外崩溃
            elif not self._browser or not self._browser.is_connected():
                should_restart = True

            # 条件3: headless 模式需要切换
            # Playwright 不支持动态切换 headless，必须重启浏览器
            elif self._current_headless != headless:
                logger.info(f"Switching Headless Mode: {headless}")
                should_restart = True

            # 如果不需要重启，直接返回，复用现有实例
            if not should_restart:
                return

            # === 执行重启流程 ===

            # 清理旧的浏览器实例（仅在同一 Loop 中才能安全关闭）
            if self._browser and self._owner_loop == current_loop:
                try:
                    await self._browser.close()
                except:
                    pass  # 忽略关闭时的异常，可能浏览器已经崩溃

            # 初始化 Playwright（仅首次调用时执行）
            # 使用 Stealth 插件包装，绕过网站的自动化检测
            if not self._playwright:
                self._stealth_context = Stealth().use_async(async_playwright())
                self._playwright = await self._stealth_context.__aenter__()

            # 带重试机制的浏览器启动
            # 网络环境不稳定时，浏览器下载/启动可能失败
            for attempt in range(self.max_retries + 1):
                try:
                    # 动态获取浏览器启动器（chromium/firefox/webkit）
                    launcher = getattr(self._playwright, self.default_browser_type)

                    # 启动浏览器实例
                    self._browser = await launcher.launch(
                        headless=headless,
                        args=self.default_launch_args,  # 传入启动参数（如禁用沙箱等）
                    )

                    # 记录当前状态，供后续检测使用
                    self._current_headless = headless
                    self._owner_loop = current_loop
                    break  # 启动成功，退出重试循环

                except Exception as e:
                    # 达到最大重试次数，抛出异常
                    if attempt == self.max_retries:
                        raise e
                    # 否则继续重试（循环自动进入下一次迭代）

    @asynccontextmanager
    async def page(
        self,
        auth_file: Optional[str] = None,
        headless: Optional[bool] = None,
        proxy: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        enable_guard: bool = True,  # 是否启用异常监控，默认启用
        auto_load_cookie: bool = True,  # 是否自动加载默认 Cookie 文件
        **context_kwargs,
    ) -> AsyncGenerator[Page, None]:
        """
        获取一个 Page 对象。

        Args:
            auth_file: Cookie 状态文件路径，用于登录态复用（None 时使用默认路径）
            headless: 是否无头模式
            proxy: 代理配置，如 {"server": "http://proxy:8080"}
            timeout: 页面默认超时（毫秒）
            enable_guard: 是否启用 PageGuard 自动监控（默认 True）
            auto_load_cookie: 是否自动加载默认 Cookie 文件（默认 True）
            **context_kwargs: 传递给 browser.new_context 的其他参数
        """
        use_headless = headless if headless is not None else self.default_headless
        await self._ensure_browser(use_headless)

        # 处理 auth_file 默认路径
        # 使用当前工作目录（运行时通常是项目根目录）下的 .auth/default.json
        if auth_file is None and auto_load_cookie:
            auth_file = os.path.join(os.getcwd(), ".auth", "default.json")

        # 构建 Context 配置
        options = {
            "viewport": self.default_viewport,
            "user_agent": self.default_user_agent,
            "ignore_https_errors": True,
            **context_kwargs,
        }
        if proxy:
            options["proxy"] = proxy
        if auth_file and os.path.exists(auth_file):
            logger.debug(f"[Engine] 自动加载 Cookie: {auth_file}")
            options["storage_state"] = auth_file

        context = await self._browser.new_context(**options)
        page = await context.new_page()
        page.set_default_timeout(timeout or self.default_timeout)

        # 自动挂载 PageGuard（使用全局注册表中的处理器）
        # 启用 Guard 时返回 GuardedPage 代理类，实现业务代码无感等待
        guard = None
        if enable_guard:
            from .guarded_page import GuardedPage

            guard = PageGuard()
            guard.attach_to_page(page)
            # 在初始导航前运行一次检查
            asyncio.create_task(guard.run_inspection(page))

            # 监听新页面事件，自动为新页面挂载 Guard
            # 这确保了通过 window.open, target="_blank" 或中间键打开的新标签页也能被监控
            def _on_new_page(new_page: Page):
                logger.debug(f"[Engine] 检测到新页面打开: {new_page.url}")
                guard.attach_to_page(new_page)
                # 新页面打开后立即执行一次巡检
                asyncio.create_task(guard.run_inspection(new_page))

            context.on("page", _on_new_page)

        try:
            # 返回 GuardedPage 代理（如果启用了 Guard）
            # 否则返回原生 Page
            if enable_guard and guard:
                yield GuardedPage(page, guard)
            else:
                yield page
        finally:
            await page.close()
            await context.close()

    async def close(self):
        """彻底关闭引擎"""
        current_loop = asyncio.get_running_loop()
        if self._browser and self._owner_loop == current_loop:
            await self._browser.close()
        if self._stealth_context and self._owner_loop == current_loop:
            await self._stealth_context.__aexit__(None, None, None)
        self._browser = None
        self._playwright = None


# ========== 全局单例管理 ==========
_browser_engine: Optional[BrowserEngine] = None
_engine_lock = asyncio.Lock()


async def get_browser_engine(**config) -> BrowserEngine:
    """
    获取全局 BrowserEngine 单例。

    首次调用时可传入配置参数初始化引擎，后续调用忽略参数返回已有实例。
    """
    global _browser_engine

    # 懒加载：仅在首次调用时创建实例
    async with _engine_lock:
        if _browser_engine is None:
            _browser_engine = BrowserEngine(**config)
        return _browser_engine

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator, Dict, List, Literal, Any
from playwright.async_api import async_playwright, Browser, Playwright, Page
from playwright_stealth import Stealth
from loguru import logger

class BrowserEngine:
    """
    异步浏览器引擎：
    1. 管理全局唯一的 Browser 实例（资源复用）。
    2. 提供 Context 级别的隔离（每个任务独立的 Cookie/代理）。
    3. 自动处理 Event Loop 崩溃恢复。
    4. 集成 playwright-stealth 反检测。
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
        self._stealth_context: Optional[Any] = None  # Stealth 上下文管理器实例
        self._current_headless: bool = default_headless
        self._lock = asyncio.Lock()
        self._owner_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # 配置存储（避免可变默认参数问题）
        self.default_headless = default_headless
        self.default_viewport = default_viewport or {"width": 1920, "height": 1080}
        self.default_user_agent = default_user_agent
        self.default_browser_type = default_browser_type
        self.max_retries = max_retries
        self.default_timeout = default_timeout
        
        # 核心反爬参数
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
        确保全局 Browser 实例存活且可用。
        注意：代理不再此处配置，移至 Context 级别。
        """
        current_loop = asyncio.get_running_loop()
        
        async with self._lock:
            should_restart = False

            # 1. 灾难恢复：Loop 变更检测
            if self._browser and self._owner_loop and self._owner_loop != current_loop:
                logger.warning(f"Event Loop changed ({id(self._owner_loop)} -> {id(current_loop)}). Restarting browser...")
                self._browser = None
                self._playwright = None
                should_restart = True

            # 2. 状态检测
            if self._browser:
                try:
                    if not self._browser.is_connected():
                        should_restart = True
                except Exception:
                    should_restart = True
            else:
                should_restart = True

            # 3. 配置变更检测
            if self._current_headless != headless:
                logger.info(f"Switching Headless Mode: {self._current_headless} -> {headless}")
                should_restart = True

            if not should_restart:
                return

            # --- 执行重启流程 ---
            
            # 关闭旧实例
            if self._browser and self._owner_loop == current_loop:
                try:
                    await self._browser.close()
                except Exception:
                    pass

            # 启动 Playwright（包装 Stealth 以自动应用反爬策略）
            if not self._playwright:
                # 使用 Stealth 包装 async_playwright，手动管理上下文
                self._stealth_context = Stealth().use_async(async_playwright())
                self._playwright = await self._stealth_context.__aenter__()

            # 启动 Browser (重试机制)
            for attempt in range(self.max_retries + 1):
                try:
                    logger.info(f"Launching {self.default_browser_type} (Headless: {headless})...")
                    
                    launcher = getattr(self._playwright, self.default_browser_type)
                    self._browser = await launcher.launch(
                        headless=headless,
                        args=self.default_launch_args,
                        # 注意：这里不传 proxy，实现全局无代理，Context 级按需代理
                    )
                    
                    self._current_headless = headless
                    self._owner_loop = current_loop
                    logger.info("Browser launched successfully.")
                    break
                except Exception as e:
                    logger.error(f"Browser launch failed (Attempt {attempt + 1}): {e}")
                    if attempt == self.max_retries:
                        raise RuntimeError(f"Failed to launch browser after {self.max_retries} retries") from e

    @asynccontextmanager
    async def page(
        self,
        auth_file: Optional[str] = None,
        headless: Optional[bool] = None,
        viewport: Optional[Dict[str, int]] = None,
        user_agent: Optional[str] = None,
        extra_http_headers: Optional[Dict[str, str]] = None,
        referer: Optional[str] = None,
        proxy: Optional[Dict[str, str]] = None,  # 代理现在在这里处理
        locale: Optional[str] = None,
        geolocation: Optional[Dict[str, float]] = None,
        permissions: Optional[List[str]] = None,
        timeout: Optional[int] = None,
        # 移除了 use_persistent_context，因为它破坏了单例模式，建议用 storage_state 代替
    ) -> AsyncGenerator[Page, None]:
        """
        获取一个功能完备的 Page 对象。
        """
        # 1. 确保底层浏览器就绪
        use_headless = headless if headless is not None else self.default_headless
        await self._ensure_browser(use_headless)

        # 2. 构建 Context 配置 (隔离环境的核心)
        context_options = {
            "viewport": viewport or self.default_viewport,
            "user_agent": user_agent or self.default_user_agent,
            "ignore_https_errors": True,
        }
        
        # 可选参数：只在非空时添加
        if extra_http_headers:
            context_options["extra_http_headers"] = extra_http_headers
        if locale:
            context_options["locale"] = locale
        if geolocation:
            context_options["geolocation"] = geolocation
        if permissions:
            context_options["permissions"] = permissions
        
        # 代理设置 (Context 级别)
        if proxy:
            context_options["proxy"] = proxy
            
        # Referer 处理
        if referer:
            if "extra_http_headers" not in context_options:
                context_options["extra_http_headers"] = {}
            context_options["extra_http_headers"]["Referer"] = referer

        # 身份状态加载 (Cookie)
        if auth_file and os.path.exists(auth_file):
            context_options["storage_state"] = auth_file
            logger.debug(f"Loaded storage state: {auth_file}")

        context = None
        page = None
        
        try:
            # 3. 创建隔离的上下文 (Ephemeral Context)
            context = await self._browser.new_context(**context_options)
            
            # 授权地理位置 (如果有)
            if geolocation:
                await context.grant_permissions(permissions or ["geolocation"])

            # 4. 创建页面
            page = await context.new_page()
            page.set_default_timeout(timeout or self.default_timeout)

            # 5. Stealth 已在 playwright 启动时自动应用，无需额外操作
            
            yield page
            
        except Exception as e:
            logger.error(f"Error during page creation/usage: {e}")
            raise
        finally:
            # 6. 资源自动回收
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

    async def close(self):
        """彻底关闭引擎"""
        current_loop = asyncio.get_running_loop()
        if self._browser and self._owner_loop == current_loop:
            try:
                await self._browser.close()
            except Exception:
                pass
        
        # 退出 Stealth 上下文管理器
        if self._stealth_context and self._owner_loop == current_loop:
            try:
                await self._stealth_context.__aexit__(None, None, None)
            except Exception:
                pass
        
        self._browser = None
        self._playwright = None
        self._stealth_context = None
        logger.info("BrowserEngine shutdown.")


# ========== 全局单例管理 ==========

_browser_engine: Optional[BrowserEngine] = None
_engine_lock = asyncio.Lock()


async def get_browser_engine(
    headless: Optional[bool] = None,
    **override_config: Any
) -> BrowserEngine:
    """
    获取全局 BrowserEngine 单例（懒加载模式）。
    
    第一次调用时会创建实例，后续调用返回同一实例。
    引擎内部已支持动态切换 headless 模式，无需重新创建实例。
    
    Args:
        headless: 是否无头模式，None 时使用默认值 True
        **override_config: 首次初始化时的其他覆盖配置，如 default_timeout 等
                          （注意：仅在首次创建时生效）
    
    Returns:
        全局共享的 BrowserEngine 实例
    
    Examples:
        >>> engine = await get_browser_engine()
        >>> async with engine.page() as page:
        ...     await page.goto("https://example.com")
    """
    global _browser_engine
    
    async with _engine_lock:
        if _browser_engine is None:
            init_headless = headless if headless is not None else True
            _browser_engine = BrowserEngine(
                default_headless=init_headless,
                **override_config
            )
            logger.info("BrowserEngine initialized (lazy mode).")
        return _browser_engine


async def shutdown_browser_engine() -> None:
    """
    关闭全局浏览器引擎。
    
    应在程序退出时调用，确保浏览器进程正确关闭。
    
    Examples:
        >>> import atexit
        >>> import asyncio
        >>> atexit.register(lambda: asyncio.run(shutdown_browser_engine()))
    """
    global _browser_engine
    
    async with _engine_lock:
        if _browser_engine is not None:
            await _browser_engine.close()
            _browser_engine = None

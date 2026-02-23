"""
登录异常处理器

功能：
1. 检测页面是否需要登录（URL关键词 + 成功元素缺失）
2. 弹出人工接管横幅
3. 混合检测登录成功（URL重定向 + Cookie变化 + 用户手动确认）
4. 自动保存登录状态到文件
"""
import os
import asyncio
from typing import Optional, List, Set
from playwright.async_api import Page
from loguru import logger
from .base import BaseAnomalyHandler
from ..task_utils import create_monitored_task

# UI 样式配置
_OVERLAY_STYLE = "position:fixed;top:0;left:0;width:100%;z-index:2147483647;font-family:sans-serif;text-align:center;padding:15px;box-shadow:0 4px 12px rgba(0,0,0,0.15);box-sizing:border-box;"
_BUTTON_STYLE = "margin-left:20px;padding:8px 24px;color:white;background-color:#28a745;border:none;border-radius:5px;cursor:pointer;font-weight:bold;"

# 通用登录弹窗选择器（用于检测弹窗存在/消失）
# 这些选择器设计为通用的，适用于大多数网站
LOGIN_POPUP_SELECTORS = [
    # iframe 相关（最常见）
    "iframe[src*='login']",
    "iframe[src*='passport']",
    "iframe[src*='signin']",
    "iframe[src*='auth']",
    # 弹窗容器
    "[class*='login-modal']",
    "[class*='login-dialog']",
    "[class*='login-box']",
    "[class*='loginModal']",
    "[class*='loginDialog']",
    # 遮罩层
    "[class*='login'][class*='mask']",
    "[class*='login'][class*='overlay']",
]


class LoginHandler(BaseAnomalyHandler):
    """
    登录异常处理器。
    
    检测登录成功的三种方式（任一满足即视为成功）：
    1. URL 重定向：URL 离开登录页关键词
    2. Cookie 变化：检测到新的认证相关 Cookie
    3. 用户手动确认：点击"我已完成登录"按钮
    """
    
    # 登录检测优先级最高
    priority = 10
    
    # 常见的认证 Cookie 名称模式
    DEFAULT_AUTH_COOKIE_PATTERNS = [
        "token", "session", "auth", "login", "user", "uid", "sid",
        "access_token", "refresh_token", "jwt", "credential"
    ]

    def __init__(
        self, 
        auth_file: Optional[str] = None,  # 默认 None，将使用项目根目录下的路径
        success_selector: Optional[str] = None,
        login_url_keywords: Optional[List[str]] = None,
        auth_cookie_patterns: Optional[List[str]] = None,
        detection_interval: float = 1.0,  # 检测间隔（秒）
        max_wait_time: float = 120.0,     # 最大等待时间（秒）
    ):
        """
        初始化登录处理器。
        
        Args:
            auth_file: Cookie 状态保存路径（默认为项目 .auth/default.json）
            success_selector: 登录成功后出现的元素选择器（可选）
            login_url_keywords: 登录页 URL 关键词列表
            auth_cookie_patterns: 认证 Cookie 名称模式列表
            detection_interval: 自动检测登录成功的轮询间隔
            max_wait_time: 等待登录完成的最大时间
        """
        # 处理 auth_file 默认路径
        # 使用当前工作目录（运行时通常是项目根目录）下的 .auth/default.json
        if auth_file is None:
            auth_file = os.path.join(os.getcwd(), '.auth', 'default.json')
        
        self.auth_file = auth_file
        self.success_selector = success_selector
        self.login_keywords = login_url_keywords or ["login", "passport", "signin", "member"]
        self.auth_cookie_patterns = auth_cookie_patterns or self.DEFAULT_AUTH_COOKIE_PATTERNS
        self.detection_interval = detection_interval
        self.max_wait_time = max_wait_time
        
        # 运行时状态
        self._initial_cookies: Set[str] = set()
        self._initial_url: str = ""
        self._user_confirmed: bool = False

    @property
    def name(self) -> str:
        return "人工登录接管"

    def _is_login_url(self, url: str) -> bool:
        """
        检查 URL 是否为登录页
        
        Args:
            url: 要检查的 URL
            
        Returns:
            bool: 是登录页返回 True
        """
        from urllib.parse import urlparse
        
        parsed_url = urlparse(url.lower())
        # 只检查域名和路径，避免误匹配查询参数中的关键词
        check_text = f"{parsed_url.netloc}{parsed_url.path}"
        
        for keyword in self.login_keywords:
            # 检查是否作为路径段出现（如 /login, /passport/）
            # 或作为子域名出现（如 login.taobao.com）
            if (f"/{keyword}" in check_text or 
                f"{keyword}." in check_text or 
                f".{keyword}" in check_text or
                check_text.endswith(f"/{keyword}")):
                return True
        return False

    async def detect(self, page: Page) -> bool:
        """
        检测是否需要登录：
        1. 主页面 URL 包含登录关键词
        2. 任意 iframe 的 URL 包含登录关键词
        3. 登录弹窗元素可见
        4. 如果指定了成功标识元素且该元素不存在
        """
        # 1. 检查主页面 URL
        if self._is_login_url(page.url):
            logger.debug(f"[登录检测] 主页面是登录页: {page.url}")
            return True
        
        # 2. 遍历所有 frames 检测 iframe 登录
        for frame in page.frames:
            if frame == page.main_frame or not frame.url:
                continue
            if self._is_login_url(frame.url):
                logger.debug(f"[登录检测] 发现登录 iframe: {frame.url}")
                return True
        
        # 3. 检查登录弹窗元素（使用统一选择器列表）
        for selector in LOGIN_POPUP_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    logger.debug(f"[登录检测] 发现登录元素: {selector}")
                    return True
            except:
                pass
        
        # 4. 检查成功标志元素 (如果已配置)
        if self.success_selector:
            element = await page.query_selector(self.success_selector)
            if not element or not await element.is_visible():
                logger.debug(f"[登录检测] 成功标识元素不存在: {self.success_selector}")
                return True
        
        return False


    async def handle(self, page: Page) -> None:
        """
        处理登录流程：
        1. 记录初始状态（URL、Cookie）
        2. 注入提示横幅
        3. 并行监控三种成功条件
        4. 任一条件满足后保存状态
        5. 统一刷新动作由 PageGuard 在 handler 结束后执行
        """
        logger.warning(">>> 触发人工登录模式 <<<")
        
        success_reason = None
        try:
            # 1. 记录初始状态
            await self._capture_initial_state(page)
            logger.debug(f"初始 URL: {self._initial_url}")
            logger.debug(f"初始 Cookie 数量: {len(self._initial_cookies)}")
            
            # 2. 等待页面加载完成后注入提示 UI
            await self._inject_banner(page)
            
            # 3. 并行监控登录成功
            success_reason = await self._wait_for_login_success(page)
            
            if success_reason:
                logger.success(f">>> 检测到登录成功: {success_reason} <<<")
                # 只有检测到成功时才保存状态
                await self._save_auth_state(page)
                
                # 4. 刷新动作由 PageGuard 在 handler 完成后统一执行
            else:
                logger.warning(">>> 等待超时，未检测到登录成功，不保存状态 <<<")
            
            # 5. 移除 UI
            await self._remove_banner(page)
            
        except Exception as e:
            logger.error(f"登录接管流程出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            # 出错时不保存状态，只尝试移除横幅
            try:
                await self._remove_banner(page)
            except:
                pass

    async def _capture_initial_state(self, page: Page) -> None:
        """记录登录前的初始状态"""
        self._initial_url = page.url.lower()
        self._user_confirmed = False
        
        # 记录当前所有 Cookie 的名称
        cookies = await page.context.cookies()
        self._initial_cookies = {c["name"] for c in cookies}

    async def _wait_for_login_success(self, page: Page) -> Optional[str]:
        """
        监控登录成功条件。
        
        判定成功的条件（任一满足）：
        1. 用户手动点击确认按钮（最高优先级）
        2. URL 离开登录页（主页面跳转场景）
        3. 登录弹窗消失 + Cookie 变化（iframe 弹窗场景）
        
        Returns:
            成功原因字符串，超时返回 None
        """
        start_time = asyncio.get_event_loop().time()
        
        # 检测是否是 iframe 弹窗场景（主页 URL 不是登录页）
        is_iframe_popup_mode = not self._is_login_url(page.url)
        if is_iframe_popup_mode:
            logger.debug("[登录等待] 识别为 iframe 弹窗模式")
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= self.max_wait_time:
                logger.warning(f"等待登录超时 ({self.max_wait_time}秒)")
                return None
            
            # 检测方式 1: 用户手动确认（最高优先级）
            if self._user_confirmed:
                return "用户点击确认按钮"
            
            # 检测方式 2: URL 重定向（主页面跳转场景）
            if not is_iframe_popup_mode:
                url_result = await self._check_url_redirect(page)
                if url_result:
                    # URL 离开登录页后，额外验证 Cookie 变化以确保真正登录成功
                    cookie_info = await self._check_cookie_change(page)
                    if cookie_info:
                        logger.info(f"[登录成功] {url_result}, {cookie_info}")
                        return url_result
                    else:
                        # URL 变化但无 Cookie，可能是刷新或失败重定向，继续等待
                        logger.debug("[URL检测] URL 变化但无新 Cookie，继续等待...")
            
            # 检测方式 3: 弹窗消失检测（iframe 弹窗场景）
            if is_iframe_popup_mode:
                popup_result = await self._check_popup_dismissed(page)
                if popup_result:
                    return popup_result
            
            # 更新横幅状态
            remaining = int(self.max_wait_time - elapsed)
            await self._update_banner_countdown(page, remaining)
            
            # 等待下一轮检测
            await asyncio.sleep(self.detection_interval)

    async def _check_popup_dismissed(self, page: Page) -> Optional[str]:
        """
        检测登录弹窗/iframe 是否已消失（表示登录完成或用户关闭）
        
        Returns:
            如果检测到弹窗消失且有 Cookie 变化，返回成功原因；否则返回 None
        """
        # 使用统一的登录弹窗选择器
        popup_exists = False
        for selector in LOGIN_POPUP_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    popup_exists = True
                    break
            except:
                pass
        
        if popup_exists:
            # 弹窗仍存在，继续等待
            return None
        
        # 弹窗消失了，检查是否有 Cookie 变化
        cookie_info = await self._check_cookie_change(page)
        if cookie_info:
            logger.info(f"[弹窗检测] 登录弹窗已消失，{cookie_info}")
            return f"登录弹窗消失 + {cookie_info}"
        
        # 弹窗消失但没有 Cookie 变化，继续等待
        return None

    async def _check_url_redirect(self, page: Page) -> Optional[str]:
        """
        检测 URL 是否已离开登录页。
        
        Returns:
            如果检测到重定向，返回描述字符串；否则返回 None
        """
        current_url = page.url.lower()
        
        # 检查是否仍在登录页
        is_still_login = self._is_login_url(current_url)
        
        # 详细调试日志
        logger.debug(f"[URL检测] 当前: {current_url[:80]}...")
        logger.debug(f"[URL检测] 初始: {self._initial_url[:80]}...")
        logger.debug(f"[URL检测] 仍在登录页: {is_still_login}, URL变化: {current_url != self._initial_url}")
        
        if not is_still_login and current_url != self._initial_url:
            logger.info(f"[URL检测] ✓ 检测到离开登录页: {page.url}")
            return f"URL 重定向到: {page.url}"
        
        return None

    async def _check_cookie_change(self, page: Page) -> Optional[str]:
        """
        检测是否有新的认证相关 Cookie 出现。
        
        Returns:
            如果检测到新 Cookie，返回描述字符串；否则返回 None
        """
        try:
            cookies = await page.context.cookies()
            current_cookie_names = {c["name"] for c in cookies}
            
            # 找出新增的 Cookie
            new_cookies = current_cookie_names - self._initial_cookies
            
            if new_cookies:
                # 检查新 Cookie 是否匹配认证模式
                auth_cookies = []
                for cookie_name in new_cookies:
                    cookie_lower = cookie_name.lower()
                    if any(pattern in cookie_lower for pattern in self.auth_cookie_patterns):
                        auth_cookies.append(cookie_name)
                
                if auth_cookies:
                    logger.debug(f"检测到新的认证 Cookie: {auth_cookies}")
                    return f"新增认证 Cookie: {', '.join(auth_cookies[:3])}"
            
            return None
        except Exception as e:
            logger.debug(f"Cookie 检测出错: {e}")
            return None

    async def _inject_banner(self, page: Page) -> None:
        """注入登录提示横幅（在所有页面）"""
        logger.debug("[横幅] 准备注入横幅到所有页面...")
        
        js_code = f"""
        () => {{
            // 检查 body 是否存在
            if (!document.body) return false;
            
            // 移除旧横幅
            const old = document.getElementById('__guard_overlay__');
            if (old) old.remove();
            
            // 创建新横幅
            const div = document.createElement('div');
            div.id = '__guard_overlay__';
            div.style.cssText = `{_OVERLAY_STYLE} background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;`;
            
            div.innerHTML = `
                <span id="__guard_msg__" style="font-size:16px;">
                    🔐 请在下方完成登录操作 | 系统正在自动检测... | 
                    <span id="__guard_countdown__">剩余 {int(self.max_wait_time)} 秒</span>
                </span>
                <button id="__guard_confirm_btn__" style="{_BUTTON_STYLE}">✓ 我已完成登录</button>
            `;
            
            document.body.appendChild(div);
            try {{
                document.body.style.marginTop = '60px';
            }} catch(e) {{}}
            
            // 绑定确认按钮事件
            document.getElementById('__guard_confirm_btn__').onclick = () => {{
                window.__guard_user_confirmed__ = true;
            }};
            
            return true;
        }}
        """
        
        # 遍历上下文中的所有页面注入
        try:
            pages = page.context.pages
            for p in pages:
                if p.is_closed(): continue
                try:
                    # 只有当页面 DOM 加载完成后才能注入
                    # 将超时设置短一点，避免卡住
                    # await p.wait_for_selector('body', timeout=2000)
                    
                    result = await p.evaluate(js_code)
                    if result:
                        logger.debug(f"[横幅] 横幅注入成功: {p.url}")
                    else:
                        logger.debug(f"[横幅] 横幅注入跳过（body 不存在）: {p.url}")
                except Exception as e:
                    logger.debug(f"[横幅] 注入跳过页面 {p.url}: {e}")
        except Exception as e:
            logger.error(f"[横幅] 遍历页面出错: {e}")
        
        # 监听用户点击确认按钮
        create_monitored_task(
            self._poll_user_confirmation(page),
            task_name="LoginHandler.poll_user_confirmation",
        )

    async def _poll_user_confirmation(self, page: Page) -> None:
        """轮询所有页面检查用户是否点击了确认按钮"""
        try:
            while not self._user_confirmed:
                for p in page.context.pages:
                    if p.is_closed(): continue
                    try:
                        confirmed = await p.evaluate("() => window.__guard_user_confirmed__ === true")
                        if confirmed:
                            self._user_confirmed = True
                            logger.debug(f"用户点击了确认按钮 (在页面 {p.url})")
                            return
                    except:
                        pass
                await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _update_banner_countdown(self, page: Page, remaining: int) -> None:
        """更新所有页面上的倒计时"""
        js_code = f"""
        () => {{
            const el = document.getElementById('__guard_countdown__');
            if (el) el.textContent = '剩余 {remaining} 秒';
        }}
        """
        try:
            pages = page.context.pages
            for p in pages:
                if p.is_closed(): continue
                try:
                    await p.evaluate(js_code)
                except:
                    pass
        except:
            pass

    async def _remove_banner(self, page: Page) -> None:
        """从所有页面移除横幅"""
        js_code = """
        () => {
            document.getElementById('__guard_overlay__')?.remove();
            document.body.style.marginTop = '';
        }
        """
        try:
            pages = page.context.pages
            for p in pages:
                if p.is_closed(): continue
                try:
                    await p.evaluate(js_code)
                except:
                    pass
        except:
            pass

    async def _save_auth_state(self, page: Page) -> None:
        """保存登录状态到文件"""
        try:
            save_dir = os.path.dirname(self.auth_file)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir)
            
            await page.context.storage_state(path=self.auth_file)
            
            # 统计保存的 Cookie 数量
            cookies = await page.context.cookies()
            logger.success(f">>> 登录状态已保存: {self.auth_file} ({len(cookies)} cookies) <<<")
            
        except Exception as e:
            logger.error(f"保存登录状态失败: {e}")


# ========== 自动注册 ==========
def _auto_register():
    """
    模块加载时自动注册默认 LoginHandler。
    检查是否已注册以避免重复创建实例（如模块被多次 import）。
    """
    from ..registry import get_registry
    
    registry = get_registry()
    handler_name = "人工登录接管"
    
    # 检查是否已注册
    if handler_name in registry.get_all_handlers():
        logger.debug(f"[LoginHandler] 处理器 '{handler_name}' 已存在，跳过重复注册")
        return
    
    # 首次注册
    registry.register(LoginHandler())

_auto_register()

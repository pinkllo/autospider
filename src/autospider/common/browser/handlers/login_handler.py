"""登录异常处理器。"""

from __future__ import annotations

import asyncio
import os
from typing import List, Optional, Set

from loguru import logger
from playwright.async_api import Page

from .base import BaseAnomalyHandler
from ..intervention import BrowserInterventionRequired, build_interrupt_payload, interrupts_enabled
from ..task_utils import create_monitored_task

_OVERLAY_STYLE = "position:fixed;top:0;left:0;width:100%;z-index:2147483647;font-family:sans-serif;text-align:center;padding:15px;box-shadow:0 4px 12px rgba(0,0,0,0.15);box-sizing:border-box;"
_BUTTON_STYLE = "margin-left:20px;padding:8px 24px;color:white;background-color:#28a745;border:none;border-radius:5px;cursor:pointer;font-weight:bold;"

LOGIN_POPUP_SELECTORS = [
    "iframe[src*='login']",
    "iframe[src*='passport']",
    "iframe[src*='signin']",
    "iframe[src*='auth']",
    "[class*='login-modal']",
    "[class*='login-dialog']",
    "[class*='login-box']",
    "[class*='loginModal']",
    "[class*='loginDialog']",
    "[class*='login'][class*='mask']",
    "[class*='login'][class*='overlay']",
]


class LoginHandler(BaseAnomalyHandler):
    priority = 10
    DEFAULT_AUTH_COOKIE_PATTERNS = [
        "token",
        "session",
        "auth",
        "login",
        "user",
        "uid",
        "sid",
        "access_token",
        "refresh_token",
        "jwt",
        "credential",
    ]

    def __init__(
        self,
        auth_file: Optional[str] = None,
        success_selector: Optional[str] = None,
        login_url_keywords: Optional[List[str]] = None,
        auth_cookie_patterns: Optional[List[str]] = None,
        detection_interval: float = 1.0,
        max_wait_time: float = 120.0,
    ):
        if auth_file is None:
            auth_file = os.path.join(os.getcwd(), ".auth", "default.json")
        self.auth_file = auth_file
        self.success_selector = success_selector
        self.login_keywords = login_url_keywords or ["login", "passport", "signin", "member"]
        self.auth_cookie_patterns = auth_cookie_patterns or self.DEFAULT_AUTH_COOKIE_PATTERNS
        self.detection_interval = detection_interval
        self.max_wait_time = max_wait_time
        self._initial_cookies: Set[str] = set()
        self._initial_url = ""
        self._user_confirmed = False

    @property
    def name(self) -> str:
        return "人工登录接管"

    def _is_login_url(self, url: str) -> bool:
        from urllib.parse import urlparse

        parsed_url = urlparse(url.lower())
        check_text = f"{parsed_url.netloc}{parsed_url.path}"
        for keyword in self.login_keywords:
            if (
                f"/{keyword}" in check_text
                or f"{keyword}." in check_text
                or f".{keyword}" in check_text
                or check_text.endswith(f"/{keyword}")
            ):
                return True
        return False

    async def detect(self, page: Page) -> bool:
        if self._is_login_url(page.url):
            logger.debug(f"[登录检测] 主页面是登录页: {page.url}")
            return True

        for frame in page.frames:
            if frame == page.main_frame or not frame.url:
                continue
            if self._is_login_url(frame.url):
                logger.debug(f"[登录检测] 发现登录 iframe: {frame.url}")
                return True

        for selector in LOGIN_POPUP_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    logger.debug(f"[登录检测] 发现登录元素: {selector}")
                    return True
            except Exception:
                pass

        if self.success_selector:
            element = await page.query_selector(self.success_selector)
            if not element or not await element.is_visible():
                logger.debug(f"[登录检测] 成功标识元素不存在: {self.success_selector}")
                return True

        return False

    async def handle(self, page: Page) -> None:
        logger.warning(">>> 触发人工登录模式 <<<")
        if interrupts_enabled(page):
            raise BrowserInterventionRequired(
                build_interrupt_payload(
                    page,
                    intervention_type="login_required",
                    handler_name=self.name,
                    message="请先完成人工登录，并确认认证状态已写入 .auth/default.json 后再 resume。",
                    details={"auth_file": self.auth_file},
                )
            )

        try:
            await self._capture_initial_state(page)
            await self._inject_banner(page)
            success_reason = await self._wait_for_login_success(page)
            if success_reason:
                logger.success(f">>> 检测到登录成功: {success_reason} <<<")
                await self._save_auth_state(page)
            else:
                logger.warning(">>> 等待超时，未检测到登录成功，不保存状态 <<<")
            await self._remove_banner(page)
        except Exception as exc:
            logger.error(f"登录接管流程出错: {exc}")
            try:
                await self._remove_banner(page)
            except Exception:
                pass

    async def _capture_initial_state(self, page: Page) -> None:
        self._initial_url = page.url.lower()
        self._user_confirmed = False
        cookies = await page.context.cookies()
        self._initial_cookies = {cookie["name"] for cookie in cookies}

    async def _wait_for_login_success(self, page: Page) -> Optional[str]:
        start_time = asyncio.get_event_loop().time()
        is_iframe_popup_mode = not self._is_login_url(page.url)
        if is_iframe_popup_mode:
            logger.debug("[登录等待] 识别为 iframe 弹窗模式")

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= self.max_wait_time:
                logger.warning(f"等待登录超时 ({self.max_wait_time}秒)")
                return None

            if self._user_confirmed:
                return "用户点击确认按钮"

            if not is_iframe_popup_mode:
                url_result = await self._check_url_redirect(page)
                if url_result:
                    cookie_info = await self._check_cookie_change(page)
                    if cookie_info:
                        logger.info(f"[登录成功] {url_result}, {cookie_info}")
                        return url_result
                    logger.debug("[URL检测] URL 变化但无新 Cookie，继续等待...")

            if is_iframe_popup_mode:
                popup_result = await self._check_popup_dismissed(page)
                if popup_result:
                    return popup_result

            remaining = int(self.max_wait_time - elapsed)
            await self._update_banner_countdown(page, remaining)
            await asyncio.sleep(self.detection_interval)

    async def _check_popup_dismissed(self, page: Page) -> Optional[str]:
        popup_exists = False
        for selector in LOGIN_POPUP_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    popup_exists = True
                    break
            except Exception:
                pass

        if popup_exists:
            return None

        cookie_info = await self._check_cookie_change(page)
        if cookie_info:
            logger.info(f"[弹窗检测] 登录弹窗已消失，{cookie_info}")
            return f"登录弹窗消失 + {cookie_info}"
        return None

    async def _check_url_redirect(self, page: Page) -> Optional[str]:
        current_url = page.url.lower()
        is_still_login = self._is_login_url(current_url)
        logger.debug(f"[URL检测] 当前: {current_url[:80]}...")
        logger.debug(f"[URL检测] 初始: {self._initial_url[:80]}...")
        logger.debug(f"[URL检测] 仍在登录页: {is_still_login}, URL变化: {current_url != self._initial_url}")

        if not is_still_login and current_url != self._initial_url:
            logger.info(f"[URL检测] ✓ 检测到离开登录页: {page.url}")
            return f"URL 重定向到: {page.url}"
        return None

    async def _check_cookie_change(self, page: Page) -> Optional[str]:
        try:
            cookies = await page.context.cookies()
            current_cookie_names = {cookie["name"] for cookie in cookies}
            new_cookies = current_cookie_names - self._initial_cookies
            if new_cookies:
                auth_cookies = []
                for cookie_name in new_cookies:
                    cookie_lower = cookie_name.lower()
                    if any(pattern in cookie_lower for pattern in self.auth_cookie_patterns):
                        auth_cookies.append(cookie_name)
                if auth_cookies:
                    logger.debug(f"检测到新的认证 Cookie: {auth_cookies}")
                    return f"新增认证 Cookie: {', '.join(auth_cookies[:3])}"
            return None
        except Exception as exc:
            logger.debug(f"Cookie 检测出错: {exc}")
            return None

    async def _inject_banner(self, page: Page) -> None:
        js_code = f"""
        () => {{
            if (!document.body) return false;
            const old = document.getElementById('__guard_overlay__');
            if (old) old.remove();
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
            try {{ document.body.style.marginTop = '60px'; }} catch(e) {{}}
            document.getElementById('__guard_confirm_btn__').onclick = () => {{
                window.__guard_user_confirmed__ = true;
            }};
            return true;
        }}
        """
        try:
            for current_page in page.context.pages:
                if current_page.is_closed():
                    continue
                try:
                    await current_page.evaluate(js_code)
                except Exception as exc:
                    logger.debug(f"[横幅] 注入跳过页面 {current_page.url}: {exc}")
        except Exception as exc:
            logger.error(f"[横幅] 遍历页面出错: {exc}")

        create_monitored_task(
            self._poll_user_confirmation(page),
            task_name="LoginHandler.poll_user_confirmation",
        )

    async def _poll_user_confirmation(self, page: Page) -> None:
        try:
            while not self._user_confirmed:
                for current_page in page.context.pages:
                    if current_page.is_closed():
                        continue
                    try:
                        confirmed = await current_page.evaluate(
                            "() => window.__guard_user_confirmed__ === true"
                        )
                        if confirmed:
                            self._user_confirmed = True
                            logger.debug(f"用户点击了确认按钮 (在页面 {current_page.url})")
                            return
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _update_banner_countdown(self, page: Page, remaining: int) -> None:
        js_code = f"""
        () => {{
            const el = document.getElementById('__guard_countdown__');
            if (el) el.textContent = '剩余 {remaining} 秒';
        }}
        """
        try:
            for current_page in page.context.pages:
                if current_page.is_closed():
                    continue
                try:
                    await current_page.evaluate(js_code)
                except Exception:
                    pass
        except Exception:
            pass

    async def _remove_banner(self, page: Page) -> None:
        js_code = """
        () => {
            document.getElementById('__guard_overlay__')?.remove();
            document.body.style.marginTop = '';
        }
        """
        try:
            for current_page in page.context.pages:
                if current_page.is_closed():
                    continue
                try:
                    await current_page.evaluate(js_code)
                except Exception:
                    pass
        except Exception:
            pass

    async def _save_auth_state(self, page: Page) -> None:
        try:
            save_dir = os.path.dirname(self.auth_file)
            if save_dir and not os.path.exists(save_dir):
                os.makedirs(save_dir)
            await page.context.storage_state(path=self.auth_file)
            cookies = await page.context.cookies()
            logger.success(f">>> 登录状态已保存: {self.auth_file} ({len(cookies)} cookies) <<<")
        except Exception as exc:
            logger.error(f"保存登录状态失败: {exc}")


def _auto_register() -> None:
    from ..registry import get_registry

    registry = get_registry()
    handler_name = "人工登录接管"
    if handler_name in registry.get_all_handlers():
        logger.debug(f"[LoginHandler] 处理器 '{handler_name}' 已存在，跳过重复注册")
        return
    registry.register(LoginHandler())


_auto_register()

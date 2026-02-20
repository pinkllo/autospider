"""
验证码/滑块异常处理器

功能：
1. 检测滑块、人机验证、验证码弹窗/iframe
2. 在检测到后进入人工接管等待
3. 验证完成后自动恢复流程
"""

from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from .base import BaseAnomalyHandler


CAPTCHA_STRONG_SELECTORS = [
    "iframe[src*='captcha']",
    "iframe[src*='nocaptcha']",
    "iframe[src*='geetest']",
    "iframe[src*='aliyun']",
    "[id*='captcha']",
    "[class*='captcha']",
    "[id*='nc_']",
    "[class*='nc_']",
    "[class*='geetest']",
    "[id*='geetest']",
    "[class*='yidun']",
    "[id*='yidun']",
    "canvas[id*='captcha']",
]

# 弱信号：很多站点也会把轮播图命名为 slider，不能单独作为验证码依据
CAPTCHA_WEAK_SLIDER_SELECTORS = [
    "[id*='slider']",
    "[class*='slider']",
]

CAPTCHA_STRONG_KEYWORDS = [
    "请完成验证",
    "安全验证",
    "滑块验证",
    "拖动滑块",
    "向右滑动",
    "请按住滑块",
    "请拖动滑块",
    "点击验证",
    "验证码",
    "人机验证",
]

CAPTCHA_HINT_KEYWORDS = [
    "captcha",
    "geetest",
    "nocaptcha",
]


class CaptchaHandler(BaseAnomalyHandler):
    """验证码/滑块处理器。"""

    priority = 20

    def __init__(self, detection_interval: float = 1.0, max_wait_time: float = 180.0):
        self.detection_interval = detection_interval
        self.max_wait_time = max_wait_time
        self._user_confirmed = False

    @property
    def name(self) -> str:
        return "验证码/滑块接管"

    async def detect(self, page: Page) -> bool:
        if page.is_closed():
            return False

        # URL 强特征
        url_lower = (page.url or "").lower()
        if any(token in url_lower for token in ("captcha", "nocaptcha", "geetest", "yidun")):
            logger.debug("[CaptchaHandler] 命中 URL 强特征")
            return True

        # iframe URL 强特征
        for frame in page.frames:
            frame_url = (frame.url or "").lower()
            if any(token in frame_url for token in ("captcha", "nocaptcha", "geetest", "yidun")):
                logger.debug("[CaptchaHandler] 命中 iframe URL 强特征")
                return True

        # DOM 强特征
        for selector in CAPTCHA_STRONG_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await self._is_actionable_visible(element):
                    # 忽略 Guard 自身注入的提示层，避免自触发死循环
                    element_id = (await element.get_attribute("id") or "").strip()
                    if element_id.startswith("__guard_"):
                        continue
                    logger.debug(f"[CaptchaHandler] 命中 DOM 强特征: {selector}")
                    return True
            except Exception:
                continue

        # 弱信号：slider 仅作为辅助，必须与验证码关键词组合命中
        weak_slider_hit = False
        for selector in CAPTCHA_WEAK_SLIDER_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await self._is_actionable_visible(element):
                    element_id = (await element.get_attribute("id") or "").strip()
                    if element_id.startswith("__guard_"):
                        continue
                    weak_slider_hit = True
                    break
            except Exception:
                continue

        # 页面文本特征（关键词）
        body_text = await self._safe_get_page_text(page)
        strong_keyword_hit = bool(
            body_text and any(keyword in body_text for keyword in CAPTCHA_STRONG_KEYWORDS)
        )
        hint_keyword_hit = bool(
            body_text and any(keyword in body_text for keyword in CAPTCHA_HINT_KEYWORDS)
        )

        if strong_keyword_hit:
            logger.debug("[CaptchaHandler] 命中文本强关键词特征")
            return True

        if weak_slider_hit and hint_keyword_hit:
            logger.debug("[CaptchaHandler] 命中 slider 弱特征 + 文本提示关键词特征")
            return True

        return False

    async def _is_actionable_visible(self, element) -> bool:
        """可见且尺寸足够大，避免被轮播小组件/装饰节点误触发。"""
        try:
            if not await element.is_visible():
                return False
            box = await element.bounding_box()
            if not box:
                return False
            return box.get("width", 0) >= 24 and box.get("height", 0) >= 24
        except Exception:
            return False

    async def handle(self, page: Page) -> None:
        logger.warning(">>> 触发验证码/滑块接管模式 <<<")
        self._user_confirmed = False
        confirm_task = None

        try:
            await self._inject_banner(page)
            confirm_task = asyncio.create_task(self._poll_user_confirmation(page))
            await self._wait_until_captcha_solved(page)
        finally:
            if confirm_task and not confirm_task.done():
                confirm_task.cancel()
                try:
                    await confirm_task
                except Exception:
                    pass
            await self._remove_banner(page)

    async def _wait_until_captcha_solved(self, page: Page) -> None:
        start = asyncio.get_running_loop().time()
        stable_not_detected = 0

        while True:
            # 人工显式确认后直接退出等待，避免因站点残留特征导致无法恢复
            if self._user_confirmed:
                logger.success("[CaptchaHandler] 用户确认已完成验证码")
                return

            elapsed = asyncio.get_running_loop().time() - start
            if elapsed >= self.max_wait_time:
                logger.warning("[CaptchaHandler] 等待验证码处理超时，继续后续流程")
                return

            # 连续两次未检测到，避免瞬时误判
            detected = await self.detect(page)
            if not detected:
                stable_not_detected += 1
            else:
                stable_not_detected = 0

            if stable_not_detected >= 2:
                logger.success("[CaptchaHandler] 验证弹窗已消失，恢复执行")
                return

            remaining = int(self.max_wait_time - elapsed)
            await self._update_banner(page, remaining)
            await asyncio.sleep(self.detection_interval)

    async def _safe_get_page_text(self, page: Page) -> str:
        try:
            text = await page.evaluate(
                """() => {
                    if (!document.body) return '';
                    const clone = document.body.cloneNode(true);
                    clone.querySelectorAll('[id^="__guard_"]').forEach(el => el.remove());
                    return (clone.innerText || '').slice(0, 5000);
                }"""
            )
            return (text or "").lower()
        except Exception:
            return ""

    async def _inject_banner(self, page: Page) -> None:
        js = f"""
        () => {{
            if (!document.body) return false;
            document.getElementById('__guard_captcha_overlay__')?.remove();
            const div = document.createElement('div');
            div.id = '__guard_captcha_overlay__';
            div.style.cssText = 'position:fixed;top:0;left:0;width:100%;z-index:2147483647;'
                + 'font-family:sans-serif;text-align:center;padding:12px;'
                + 'background:#ff9800;color:#111;box-shadow:0 2px 10px rgba(0,0,0,.25);';
            div.innerHTML = `
                <span>⚠ 检测到验证码/滑块，请先人工完成验证（剩余 <b id="__guard_captcha_countdown__">{int(self.max_wait_time)}</b> 秒）</span>
                <button id="__guard_captcha_confirm__"
                        style="margin-left:12px;padding:6px 16px;border:0;border-radius:4px;background:#2e7d32;color:#fff;cursor:pointer;">
                    我已完成验证
                </button>`;
            document.body.appendChild(div);
            const btn = document.getElementById('__guard_captcha_confirm__');
            if (btn) {{
                btn.onclick = () => {{ window.__guard_captcha_confirmed__ = true; }};
            }}
            return true;
        }}
        """
        for p in page.context.pages:
            if p.is_closed():
                continue
            try:
                await p.evaluate(js)
            except Exception:
                pass

    async def _update_banner(self, page: Page, remaining: int) -> None:
        js = f"""
        () => {{
            const el = document.getElementById('__guard_captcha_countdown__');
            if (el) el.textContent = '{remaining}';
        }}
        """
        for p in page.context.pages:
            if p.is_closed():
                continue
            try:
                await p.evaluate(js)
            except Exception:
                pass

    async def _poll_user_confirmation(self, page: Page) -> None:
        try:
            while not self._user_confirmed:
                for p in page.context.pages:
                    if p.is_closed():
                        continue
                    try:
                        confirmed = await p.evaluate("() => window.__guard_captcha_confirmed__ === true")
                        if confirmed:
                            self._user_confirmed = True
                            return
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _remove_banner(self, page: Page) -> None:
        js = "() => document.getElementById('__guard_captcha_overlay__')?.remove()"
        for p in page.context.pages:
            if p.is_closed():
                continue
            try:
                await p.evaluate(js)
            except Exception:
                pass


def _auto_register() -> None:
    from ..registry import get_registry

    registry = get_registry()
    name = "验证码/滑块接管"
    if name in registry.get_all_handlers():
        return
    registry.register(CaptchaHandler())


_auto_register()

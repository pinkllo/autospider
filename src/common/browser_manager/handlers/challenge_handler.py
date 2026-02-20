"""
通用风控挑战页处理器

覆盖场景：
- Cloudflare / hCaptcha / reCAPTCHA
- 各类“验证你是人类”“robot check”挑战页
"""

from __future__ import annotations

import asyncio

from loguru import logger
from playwright.async_api import Page

from .base import BaseAnomalyHandler


CHALLENGE_SELECTORS = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "[id*='cf-challenge']",
    "[class*='cf-challenge']",
    "[class*='challenge-form']",
    "[id*='challenge']",
    "[class*='challenge']",
]

CHALLENGE_KEYWORDS = [
    "checking your browser",
    "verify you are human",
    "are you human",
    "robot check",
    "security check",
    "cloudflare",
    "hcaptcha",
    "recaptcha",
    "请证明你是人类",
    "人机验证",
    "安全校验",
]


class ChallengeHandler(BaseAnomalyHandler):
    """通用挑战页接管处理器。"""

    priority = 30

    def __init__(self, detection_interval: float = 1.0, max_wait_time: float = 180.0):
        self.detection_interval = detection_interval
        self.max_wait_time = max_wait_time
        self._user_confirmed = False

    @property
    def name(self) -> str:
        return "风控挑战接管"

    async def detect(self, page: Page) -> bool:
        if page.is_closed():
            return False

        url_lower = (page.url or "").lower()
        if any(token in url_lower for token in ("challenge", "cf-challenge", "recaptcha", "hcaptcha")):
            return True

        for selector in CHALLENGE_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    # 忽略 Guard 自身注入的提示层，避免自触发死循环
                    element_id = (await element.get_attribute("id") or "").strip()
                    if element_id.startswith("__guard_"):
                        continue
                    return True
            except Exception:
                continue

        body_text = await self._safe_get_page_text(page)
        if body_text and any(keyword in body_text for keyword in CHALLENGE_KEYWORDS):
            return True

        return False

    async def handle(self, page: Page) -> None:
        logger.warning(">>> 触发通用风控挑战接管模式 <<<")
        self._user_confirmed = False
        confirm_task = None
        try:
            await self._inject_banner(page)
            confirm_task = asyncio.create_task(self._poll_user_confirmation(page))
            await self._wait_until_cleared(page)
        finally:
            if confirm_task and not confirm_task.done():
                confirm_task.cancel()
                try:
                    await confirm_task
                except Exception:
                    pass
            await self._remove_banner(page)

    async def _wait_until_cleared(self, page: Page) -> None:
        start = asyncio.get_running_loop().time()
        stable_not_detected = 0

        while True:
            # 人工显式确认后直接退出等待，避免残留特征导致无法恢复
            if self._user_confirmed:
                logger.success("[ChallengeHandler] 用户确认挑战已处理")
                return

            elapsed = asyncio.get_running_loop().time() - start
            if elapsed >= self.max_wait_time:
                logger.warning("[ChallengeHandler] 等待挑战页处理超时，继续后续流程")
                return

            detected = await self.detect(page)
            if not detected:
                stable_not_detected += 1
            else:
                stable_not_detected = 0

            if stable_not_detected >= 2:
                logger.success("[ChallengeHandler] 挑战页特征已消失，恢复执行")
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
            document.getElementById('__guard_challenge_overlay__')?.remove();
            const div = document.createElement('div');
            div.id = '__guard_challenge_overlay__';
            div.style.cssText = 'position:fixed;top:0;left:0;width:100%;z-index:2147483647;'
                + 'font-family:sans-serif;text-align:center;padding:12px;'
                + 'background:#ffb300;color:#111;box-shadow:0 2px 10px rgba(0,0,0,.25);';
            div.innerHTML = `
                <span>⚠ 检测到风控挑战页，请人工完成验证（剩余 <b id="__guard_challenge_countdown__">{int(self.max_wait_time)}</b> 秒）</span>
                <button id="__guard_challenge_confirm__"
                        style="margin-left:12px;padding:6px 16px;border:0;border-radius:4px;background:#2e7d32;color:#fff;cursor:pointer;">
                    我已完成验证
                </button>`;
            document.body.appendChild(div);
            const btn = document.getElementById('__guard_challenge_confirm__');
            if (btn) {{
                btn.onclick = () => {{ window.__guard_challenge_confirmed__ = true; }};
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
            const el = document.getElementById('__guard_challenge_countdown__');
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
                        confirmed = await p.evaluate("() => window.__guard_challenge_confirmed__ === true")
                        if confirmed:
                            self._user_confirmed = True
                            return
                    except Exception:
                        pass
                await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _remove_banner(self, page: Page) -> None:
        js = "() => document.getElementById('__guard_challenge_overlay__')?.remove()"
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
    name = "风控挑战接管"
    if name in registry.get_all_handlers():
        return
    registry.register(ChallengeHandler())


_auto_register()

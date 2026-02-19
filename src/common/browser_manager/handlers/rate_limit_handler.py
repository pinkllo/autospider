"""
频率限制处理器（Rate Limit）

功能：
1. 检测“访问过快/限流/系统繁忙/429”等页面信号
2. 自动退避等待并尝试刷新
3. 按域名累积退避级别，降低再次触发概率
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from loguru import logger
from playwright.async_api import Page

from .base import BaseAnomalyHandler


RATE_LIMIT_KEYWORDS = [
    "访问过于频繁",
    "操作太频繁",
    "请求过于频繁",
    "请稍后再试",
    "系统繁忙",
    "请求太快",
    "too many requests",
    "rate limit",
    "429",
]

RATE_LIMIT_SELECTORS = [
    "[class*='rate-limit']",
    "[class*='too-many']",
    "[id*='rate-limit']",
    "[id*='too-many']",
]


class RateLimitHandler(BaseAnomalyHandler):
    """频率限制处理器。"""

    priority = 40

    # 按域名记录退避级别
    _domain_strikes: dict[str, int] = {}

    def __init__(
        self,
        base_backoff_s: float = 3.0,
        max_backoff_s: float = 60.0,
        recovery_decay_s: float = 120.0,
    ):
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s
        self.recovery_decay_s = recovery_decay_s
        self._last_trigger_at: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "频率限制退避"

    async def detect(self, page: Page) -> bool:
        if page.is_closed():
            return False

        url_lower = (page.url or "").lower()
        if "/429" in url_lower or "too-many-requests" in url_lower:
            return True

        for selector in RATE_LIMIT_SELECTORS:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    return True
            except Exception:
                continue

        text = await self._safe_get_page_text(page)
        if text and any(keyword in text for keyword in RATE_LIMIT_KEYWORDS):
            return True

        return False

    async def handle(self, page: Page) -> None:
        domain = self._get_domain(page.url)
        now = asyncio.get_running_loop().time()

        # 长时间未触发则衰减级别，避免永久升高
        last = self._last_trigger_at.get(domain)
        if last is not None and now - last > self.recovery_decay_s:
            self._domain_strikes[domain] = max(0, self._domain_strikes.get(domain, 0) - 1)

        strikes = self._domain_strikes.get(domain, 0) + 1
        self._domain_strikes[domain] = strikes
        self._last_trigger_at[domain] = now

        backoff = min(self.max_backoff_s, self.base_backoff_s * (2 ** (strikes - 1)))
        logger.warning(
            "[RateLimitHandler] 检测到频率限制: domain=%s strikes=%s backoff=%.1fs",
            domain,
            strikes,
            backoff,
        )

        await asyncio.sleep(backoff)

        # 统一刷新动作由 PageGuard 在 handler 完成后执行，避免重复 reload

    async def _safe_get_page_text(self, page: Page) -> str:
        try:
            text = await page.evaluate(
                "() => document.body ? document.body.innerText.slice(0, 5000) : ''"
            )
            return (text or "").lower()
        except Exception:
            return ""

    def _get_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower() or "unknown"
        except Exception:
            return "unknown"


def _auto_register() -> None:
    from ..registry import get_registry

    registry = get_registry()
    name = "频率限制退避"
    if name in registry.get_all_handlers():
        return
    registry.register(RateLimitHandler())


_auto_register()

"""频率限制处理器。"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from playwright.async_api import Page
from autospider.common.logger import get_logger

from .base import BaseAnomalyHandler

logger = get_logger(__name__)

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
    priority = 40
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
        return bool(text and any(keyword in text for keyword in RATE_LIMIT_KEYWORDS))

    async def handle(self, page: Page) -> None:
        domain = self._get_domain(page.url)
        now = asyncio.get_running_loop().time()
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

    async def _safe_get_page_text(self, page: Page) -> str:
        try:
            text = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 5000) : ''")
            return (text or "").lower()
        except Exception:
            return ""

    def _get_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower() or "unknown"
        except Exception:
            return "unknown"

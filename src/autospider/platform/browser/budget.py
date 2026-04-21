"""Process-local browser budget primitives."""

from __future__ import annotations

import asyncio


class BrowserBudget:
    """Process-local browser budget shared by thread/budget key."""

    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self._semaphore = asyncio.Semaphore(self.limit)

    async def acquire(self) -> None:
        await self._semaphore.acquire()

    def release(self) -> None:
        self._semaphore.release()


_BROWSER_BUDGETS: dict[str, BrowserBudget] = {}
_BROWSER_BUDGET_LOCK = asyncio.Lock()


async def get_browser_budget(*, budget_key: str, limit: int) -> BrowserBudget:
    key = str(budget_key or "").strip() or f"default:{limit}"
    normalized_limit = max(1, int(limit))
    async with _BROWSER_BUDGET_LOCK:
        existing = _BROWSER_BUDGETS.get(key)
        if existing is not None and existing.limit == normalized_limit:
            return existing
        budget = BrowserBudget(normalized_limit)
        _BROWSER_BUDGETS[key] = budget
        return budget


__all__ = ["BrowserBudget", "get_browser_budget"]

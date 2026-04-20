from __future__ import annotations

from abc import ABC, abstractmethod

from playwright.async_api import Page


class BaseAnomalyHandler(ABC):
    """异常处理抽象基类。"""

    priority: int = 100
    enabled: bool = True

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def detect(self, page: Page) -> bool:
        pass

    @abstractmethod
    async def handle(self, page: Page) -> None:
        pass

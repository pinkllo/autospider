"""全局异常处理器注册表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from .handlers.base import BaseAnomalyHandler


class HandlerRegistry:
    """处理器注册表单例。"""

    _instance: "HandlerRegistry | None" = None

    def __new__(cls) -> "HandlerRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: dict[str, "BaseAnomalyHandler"] = {}
            cls._instance._disabled: set[str] = set()
        return cls._instance

    def register(self, handler: "BaseAnomalyHandler") -> None:
        name = handler.name
        if name in self._handlers:
            logger.warning(f"[Registry] 处理器 '{name}' 已存在，将被覆盖")
        self._handlers[name] = handler
        logger.debug(f"[Registry] 已注册处理器: {name} (priority={handler.priority})")

    def unregister(self, name: str) -> bool:
        if name in self._handlers:
            del self._handlers[name]
            self._disabled.discard(name)
            logger.debug(f"[Registry] 已移除处理器: {name}")
            return True
        return False

    def enable(self, name: str) -> bool:
        if name in self._handlers:
            self._disabled.discard(name)
            logger.debug(f"[Registry] 已启用处理器: {name}")
            return True
        return False

    def disable(self, name: str) -> bool:
        if name in self._handlers:
            self._disabled.add(name)
            logger.debug(f"[Registry] 已禁用处理器: {name}")
            return True
        return False

    def get_handlers(self) -> list["BaseAnomalyHandler"]:
        enabled_handlers = [handler for name, handler in self._handlers.items() if name not in self._disabled]
        return sorted(enabled_handlers, key=lambda handler: handler.priority)

    def get_all_handlers(self) -> dict[str, "BaseAnomalyHandler"]:
        return self._handlers.copy()

    def is_enabled(self, name: str) -> bool:
        return name in self._handlers and name not in self._disabled

    def clear(self) -> None:
        self._handlers.clear()
        self._disabled.clear()


def get_registry() -> HandlerRegistry:
    return HandlerRegistry()


def register_handler(handler: "BaseAnomalyHandler") -> None:
    get_registry().register(handler)


def get_handlers() -> list["BaseAnomalyHandler"]:
    return get_registry().get_handlers()


def enable_handler(name: str) -> bool:
    return get_registry().enable(name)


def disable_handler(name: str) -> bool:
    return get_registry().disable(name)


def clear_handlers() -> None:
    get_registry().clear()
